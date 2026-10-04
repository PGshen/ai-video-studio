"""worker 进程入口：成片渲染任务循环（M2 T5，design §5.3/§10）。

独立进程，和 api 进程共用 `data/studio.db`、`data/blobs/`、`data/projects/<id>/`。
主循环：`run_forever` 反复调用 `run_once`；`run_once` 是单次迭代（方便测试），
流程是 reap 过期心跳 → 领取一条 `final_render` 任务 → 读工作区里的叙事产物
（`narrative/narrative.json`/`timing.json`，决策记录 D14）和每个镜头的代码
（`animation/scenes/<id>.py`）→ 把全部镜头放进同一个 MainScene，用
`ManimRenderEngine.render` 一次全画质渲染（镜头间元素通过 `self.xxx` 延续，不能
逐镜头单独渲染；命中 `.cache/render_cache/` 里的缓存则跳过，决策记录 D14）→ 写
`output/final.mp4` + `output/final.json` → `complete`/`fail`。成片不叠字幕
（ADR 0016）。

`worker` 不依赖 `agent`/`stages`/`api`/`main`（ARCHITECTURE §2 依赖表），所以
叙事产物直接读工作区顶层的 `narrative/` 目录（该阶段定稿后的产物本来就留在
那里，不是只有 `upstream/` 物化才能读到），不走 `agent.stage_flow` 那套只服务
于 agent 轮次的上游物化机制（决策记录 D14）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from studio.config import get_settings
from studio.db.engine import make_engine, migrate
from studio.db.repo.projects import get_project
from studio.engines.render.base import (
    RenderEngine,
    RenderRequest,
    RenderResult,
    RenderResultWithBytes,
    SceneAudio,
    SceneInput,
)
from studio.engines.render.manim import ManimRenderEngine
from studio.engines.render.manim.process import failed_scene_index
from studio.jobs import claim_next, complete, fail, heartbeat, reap_stale_running
from studio.worker_html import HtmlBackend, HtmlJobError, real_backend, run_html_job
from studio.workspace import (
    BlobStore,
    ScopeError,
    create_snapshot,
    project_dir,
    read_text,
    safe_path,
)

logger = logging.getLogger(__name__)

_JOB_TYPE = "final_render"
_QUALITY = "final"
_ENGINE_VERSION = "manim-v2"
"""缓存键的一部分（决策记录 D14）；改动渲染逻辑（脚本拼装/画幅约定等）时要 bump，
让旧缓存自然失效，不用手动清理 `.cache/render_cache/`。"""
_DEFAULT_RESOLUTION = (1920, 1080)
_DEFAULT_FPS = 30
_HEARTBEAT_TIMEOUT_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 2.0
_TICK_INTERVAL_SECONDS = 15.0


class SceneDataError(RuntimeError):
    """叙事产物缺失，或某个镜头缺代码/音频——worker 无法开始渲染这个任务。"""


class WorkerRenderError(RuntimeError):
    """渲染/拼接/叠字幕某一步失败，消息里点名具体镜头（如果失败发生在镜头渲染阶段）。"""


@dataclass(frozen=True, slots=True)
class _ScenePlan:
    """一个镜头渲染所需的全部输入，从工作区读出后打包备用。"""

    scene_id: str
    scene_index: int
    code: str
    narration: str
    description: str
    audio_path: Path
    audio_hash: str
    duration_seconds: float


def _load_scene_plans(workdir: Path) -> list[_ScenePlan]:
    """读 `narrative/narrative.json`+`timing.json`（工作区顶层的定稿产物，不经
    `upstream/`，见模块 docstring）和每个镜头的 `animation/scenes/<id>.py`。
    """
    try:
        narrative = json.loads(read_text(workdir, "narrative/narrative.json"))
        timing = json.loads(read_text(workdir, "narrative/timing.json"))
    except FileNotFoundError as exc:
        raise SceneDataError(f"读取叙事产物失败：{exc}") from exc

    timing_by_id = {scene["id"]: scene for scene in timing.get("scenes", [])}

    plans: list[_ScenePlan] = []
    for index, scene in enumerate(narrative.get("scenes", [])):
        scene_id = scene["id"]
        timing_scene = timing_by_id.get(scene_id)
        if timing_scene is None:
            raise SceneDataError(f"镜头 {scene_id}：timing.json 缺少对应记录")

        code_relpath = f"animation/scenes/{scene_id}.py"
        try:
            code = read_text(workdir, code_relpath)
        except FileNotFoundError as exc:
            raise SceneDataError(f"镜头 {scene_id}：缺少代码文件 {code_relpath}") from exc
        if not code.strip():
            raise SceneDataError(f"镜头 {scene_id}：代码文件为空（{code_relpath}）")

        try:
            audio_path = safe_path(workdir, timing_scene["audio_path"])
        except ScopeError as exc:
            raise SceneDataError(
                f"镜头 {scene_id}：音频路径不合法 {timing_scene['audio_path']}"
            ) from exc
        if not audio_path.is_file():
            raise SceneDataError(f"镜头 {scene_id}：音频文件不存在 {timing_scene['audio_path']}")

        plans.append(
            _ScenePlan(
                scene_id=scene_id,
                scene_index=index,
                code=code,
                narration=scene.get("narration", ""),
                description=scene.get("visual_intent", ""),
                audio_path=audio_path,
                audio_hash=str(timing_scene["audio_hash"]),
                duration_seconds=float(timing_scene["duration_seconds"]),
            )
        )

    if not plans:
        raise SceneDataError("narrative.json 里没有任何镜头")
    return plans


def _cache_dir(workdir: Path) -> Path:
    """渲染缓存目录：`.cache/` 已经是 `workspace.layout.EXCLUDED_TOP_DIRS` 里
    "不参与快照、不受越界检查约束"的顶层目录（决策记录 D14），不用新建约定。
    """
    return workdir / ".cache" / "render_cache"


def _cache_key(plans: list[_ScenePlan]) -> str:
    """整条成片的缓存键：按顺序包含每个镜头的代码与音频哈希。

    镜头之间会通过 `self.xxx` 延续画面元素，后面镜头的画面依赖前面镜头的代码，
    所以缓存粒度只能是整条成片，不能按单个镜头缓存。
    """
    parts = [
        f"{hashlib.sha256(plan.code.encode('utf-8')).hexdigest()}:{plan.audio_hash}"
        for plan in plans
    ]
    raw = f"{'|'.join(parts)}:{_QUALITY}:{_ENGINE_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _render_and_cache(
    render_engine: RenderEngine,
    workdir: Path,
    plans: list[_ScenePlan],
    *,
    resolution: tuple[int, int],
    fps: int,
    on_tick: Callable[[], None],
) -> Path:
    """把全部镜头放进同一个 MainScene 一次渲染（全画质，含音频），命中缓存则直接复用。

    不能逐镜头单独渲染：镜头间的画面元素是通过 `self.xxx` 延续的（见动画阶段
    提示词"元素默认可以跨镜头保留"），单独渲染后面的镜头会因为缺少前面镜头建立
    的状态而 AttributeError。`on_tick` 在渲染期间被周期性调用（续心跳）。
    """
    key = _cache_key(plans)
    cache_path = _cache_dir(workdir) / f"{key}.mp4"
    if cache_path.is_file():
        return cache_path

    request = RenderRequest(
        scenes=[
            SceneInput(
                scene_index=plan.scene_index,
                narration=plan.narration,
                description=plan.description,
                code=plan.code,
                audio=SceneAudio(
                    scene_index=plan.scene_index,
                    audio_path=str(plan.audio_path),
                    duration_seconds=plan.duration_seconds,
                ),
            )
            for plan in plans
        ],
        output_format="mp4",
        resolution=resolution,
        fps=fps,
    )
    result = await _with_ticks(render_engine.render(request), on_tick)
    if not result.success:
        raise WorkerRenderError(_describe_render_failure(plans, result))
    assert isinstance(result, RenderResultWithBytes)  # success 时 render() 总是带 video_bytes

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(".mp4.tmp")
    tmp_path.write_bytes(result.video_bytes)
    tmp_path.replace(cache_path)  # 写完再原子改名，中途崩溃不会留下半份缓存文件
    return cache_path


def _describe_render_failure(plans: list[_ScenePlan], result: RenderResult) -> str:
    """失败信息点名具体镜头：从 traceback 的 `_scene_N` 帧反查镜头 id。"""
    message = result.error_message or ""
    index = failed_scene_index(f"{message}\n{result.render_log}")
    if index is not None and index < len(plans):
        return f"镜头 {plans[index].scene_id} 渲染失败：{message}"
    return f"成片渲染失败：{message}"


async def _with_ticks[T](work: Awaitable[T], on_tick: Callable[[], None]) -> T:
    """等待 `work` 期间每隔 `_TICK_INTERVAL_SECONDS` 调一次 `on_tick`（单次整片渲染
    可能远超心跳超时，不续心跳会被 `reap_stale_running` 当成死任务）。
    """
    task = asyncio.ensure_future(work)
    while True:
        done, _ = await asyncio.wait({task}, timeout=_TICK_INTERVAL_SECONDS)
        if done:
            return task.result()
        on_tick()


async def run_once(
    engine: Engine,
    blobs: BlobStore,
    *,
    data_dir: Path,
    render_engine: RenderEngine | None = None,
    resolution: tuple[int, int] = _DEFAULT_RESOLUTION,
    fps: int = _DEFAULT_FPS,
    heartbeat_timeout_seconds: float = _HEARTBEAT_TIMEOUT_SECONDS,
    html_backend: HtmlBackend | None = None,
) -> bool:
    """主循环的单次迭代（方便测试；`run_forever` 反复调用它）。

    没有任务可领时返回 `False`；领到一条任务后（无论最终成功还是失败）返回
    `True`。心跳过期的 `running` 任务在每次调用时都会被 reap 一次——单 worker
    进程同一时刻最多一个 `running` 任务，重复 reap 只是幂等的空查询，比单独
    维护"是否已经在进程启动时 reap 过"的状态更简单（决策记录 D14）。
    """
    reap_stale_running(engine, type=_JOB_TYPE, heartbeat_timeout_seconds=heartbeat_timeout_seconds)

    job = claim_next(engine, type=_JOB_TYPE)
    if job is None:
        return False

    logger.info("[worker] 领取任务 %s（项目 %s）", job.id, job.project_id)
    project = get_project(engine, job.project_id)
    if project is not None and project.settings.get("engine") == "html":
        await _run_html(engine, blobs, job.id, job.project_id, data_dir, fps, html_backend)
        return True

    engine_instance = render_engine if render_engine is not None else ManimRenderEngine()
    workdir = project_dir(data_dir, job.project_id)
    heartbeat(engine, job.id)

    try:
        plans = _load_scene_plans(workdir)
    except SceneDataError as exc:
        logger.warning("[worker] 任务 %s 失败：%s", job.id, exc)
        fail(engine, job.id, error=str(exc))
        return True

    # 先拍一份快照，保证 final.json 记录的 snapshot_id 精确对应本次渲染读到的
    # 内容（`create_snapshot` 内容不变时直接返回已有快照，不会产生重复记录）。
    snapshot = create_snapshot(engine, blobs, job.project_id, reason="final_render")

    try:
        rendered = await _render_and_cache(
            engine_instance,
            workdir,
            plans,
            resolution=resolution,
            fps=fps,
            on_tick=lambda: heartbeat(engine, job.id),
        )

        output_dir = workdir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / "final.mp4"

        shutil.copyfile(rendered, final_path)
    except WorkerRenderError as exc:
        logger.warning("[worker] 任务 %s 失败：%s", job.id, exc)
        fail(engine, job.id, error=str(exc))
        return True

    final_meta = {
        "snapshot_id": snapshot.id,
        "scene_hashes": {
            plan.scene_id: hashlib.sha256(plan.code.encode("utf-8")).hexdigest() for plan in plans
        },
        "rendered_at": datetime.now(UTC).isoformat(),
    }
    (output_dir / "final.json").write_text(
        json.dumps(final_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    complete(engine, job.id, result={"output_path": "output/final.mp4"})
    logger.info("[worker] 任务 %s 完成", job.id)
    return True


async def _run_html(
    engine: Engine,
    blobs: BlobStore,
    job_id: str,
    project_id: str,
    data_dir: Path,
    fps: int,
    backend: HtmlBackend | None,
) -> None:
    heartbeat(engine, job_id)
    try:
        await run_html_job(
            engine,
            blobs,
            job_id=job_id,
            project_id=project_id,
            workdir=project_dir(data_dir, project_id),
            backend=backend if backend is not None else real_backend(),
            fps=fps,
        )
    except HtmlJobError as exc:
        logger.warning("[worker] 任务 %s 失败：%s", job_id, exc)
        fail(engine, job_id, error=str(exc))
        return
    complete(engine, job_id, result={"output_path": "output/final.mp4"})
    logger.info("[worker] 任务 %s 完成", job_id)


async def run_forever(
    engine: Engine,
    blobs: BlobStore,
    *,
    data_dir: Path,
    poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
) -> None:
    """无限轮询循环：领不到任务时睡一段时间再试。"""
    logger.info("[worker] 已启动，轮询间隔 %.1fs", poll_interval_seconds)
    while True:
        claimed = await run_once(engine, blobs, data_dir=data_dir)
        if not claimed:
            await asyncio.sleep(poll_interval_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(levelname)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.data_dir / "studio.db")
    migrate(engine)
    blobs = BlobStore(settings.data_dir / "blobs")
    try:
        asyncio.run(run_forever(engine, blobs, data_dir=settings.data_dir))
    except KeyboardInterrupt:
        logger.info("[worker] 收到中断信号，退出")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
