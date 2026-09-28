"""worker 进程入口：成片渲染任务循环（M2 T5，design §5.3/§10）。

独立进程，和 api 进程共用 `data/studio.db`、`data/blobs/`、`data/projects/<id>/`。
主循环：`run_forever` 反复调用 `run_once`；`run_once` 是单次迭代（方便测试），
流程是 reap 过期心跳 → 领取一条 `final_render` 任务 → 读工作区里的叙事产物
（`narrative/narrative.json`/`timing.json`，决策记录 D14）和每个镜头的代码
（`animation/scenes/<id>.py`）→ 逐镜头用 `ManimRenderEngine.render` 全画质渲染
（命中 `.cache/render_cache/` 里的缓存则跳过，决策记录 D14）→ 拼接 → 按镜头
旁白叠加字幕（决策记录 D15：本机 ffmpeg 没有编译 drawtext/subtitles 滤镜，
改用 Pillow 画字幕图 + `overlay` 滤镜叠加）→ 写 `output/final.mp4` +
`output/final.json` → `complete`/`fail`。

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
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import Engine

from studio.config import get_settings
from studio.db.engine import make_engine, migrate
from studio.engines.render.base import (
    RenderEngine,
    RenderRequest,
    RenderResultWithBytes,
    SceneAudio,
    SceneInput,
)
from studio.engines.render.manim import ManimRenderEngine
from studio.engines.render.manim.keyframes import probe_duration_seconds
from studio.jobs import claim_next, complete, fail, heartbeat, reap_stale_running, update_progress
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
_ENGINE_VERSION = "manim-v1"
"""缓存键的一部分（决策记录 D14）；改动渲染逻辑（脚本拼装/画幅约定等）时要 bump，
让旧缓存自然失效，不用手动清理 `.cache/render_cache/`。"""
_DEFAULT_RESOLUTION = (1920, 1080)
_DEFAULT_FPS = 30
_HEARTBEAT_TIMEOUT_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 2.0

_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
"""字幕图片用的中文字体候选路径（决策记录 D15），按存在与否取第一个命中的。"""


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


def _cache_key(plan: _ScenePlan) -> str:
    code_hash = hashlib.sha256(plan.code.encode("utf-8")).hexdigest()
    raw = f"{code_hash}:{plan.audio_hash}:{_QUALITY}:{_ENGINE_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _render_and_cache_scene(
    render_engine: RenderEngine,
    workdir: Path,
    plan: _ScenePlan,
    *,
    resolution: tuple[int, int],
    fps: int,
) -> Path:
    """渲染一个镜头（全画质，含音频），命中缓存则直接返回缓存文件路径。"""
    cache_path = _cache_dir(workdir) / f"{_cache_key(plan)}.mp4"
    if cache_path.is_file():
        return cache_path

    scene_input = SceneInput(
        scene_index=0,
        narration=plan.narration,
        description=plan.description,
        code=plan.code,
        audio=SceneAudio(
            scene_index=0, audio_path=str(plan.audio_path), duration_seconds=plan.duration_seconds
        ),
    )
    request = RenderRequest(
        scenes=[scene_input], output_format="mp4", resolution=resolution, fps=fps
    )
    result = await render_engine.render(request)
    if not result.success:
        raise WorkerRenderError(f"镜头 {plan.scene_id} 渲染失败：{result.error_message}")
    assert isinstance(result, RenderResultWithBytes)  # success 时 render() 总是带 video_bytes

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(".mp4.tmp")
    tmp_path.write_bytes(result.video_bytes)
    tmp_path.replace(cache_path)  # 写完再原子改名，中途崩溃不会留下半份缓存文件
    return cache_path


async def _run_subprocess(cmd: list[str], *, error_prefix: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise WorkerRenderError(f"{error_prefix}：{stderr.decode(errors='replace')[-1000:]}")


async def _concat_clips(clip_paths: list[Path], workdir: Path) -> Path:
    """把逐镜头渲染出的小片段按顺序拼成一条视频（音频已经通过 `add_sound` 嵌在
    每个片段里，拼接不需要单独处理音轨）。只有一个镜头时不用真的拼接。
    """
    if len(clip_paths) == 1:
        return clip_paths[0]

    cache_dir = _cache_dir(workdir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    list_path = cache_dir / "concat_list.txt"
    list_path.write_text(
        "".join(f"file '{path.resolve()}'\n" for path in clip_paths), encoding="utf-8"
    )
    concat_path = cache_dir / "concat_output.mp4"

    await _run_subprocess(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(concat_path),
        ],
        error_prefix="拼接镜头失败",
    )
    return concat_path


def _find_cjk_font() -> str:
    for candidate in _CJK_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise WorkerRenderError(
        f"找不到可用的中文字体，无法生成字幕图片（已尝试：{', '.join(_CJK_FONT_CANDIDATES)}）"
    )


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """按像素宽度逐字换行（中文没有空格分词，不能按单词换行）。"""
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width > max_width and current:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _render_subtitle_png(text: str, resolution: tuple[int, int], out_path: Path) -> None:
    """画一张跟成片同分辨率的透明字幕图：文字在下方居中，黑边白字保证可读性。"""
    width, height = resolution
    font = ImageFont.truetype(_find_cjk_font(), max(width // 32, 16))

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    lines = _wrap_text(draw, text, font, max_width=int(width * 0.86))

    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 6
    y = height - line_height * len(lines) - int(height * 0.07)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (0, 0)):
            fill = (255, 255, 255, 255) if (dx, dy) == (0, 0) else (0, 0, 0, 255)
            draw.text((x + dx, y + dy), line, font=font, fill=fill)
        y += line_height

    image.save(out_path)


async def _burn_subtitles(
    video_path: Path,
    plans: list[_ScenePlan],
    scene_durations: list[float],
    output_path: Path,
    *,
    resolution: tuple[int, int],
) -> None:
    """按镜头旁白硬编码时间轴叠加字幕（决策记录 D15，design §10 的"加字幕"）：
    每个镜头的完整旁白文本，显示区间是该镜头在拼接后成片里的起止时间——由
    `scene_durations`（ffprobe 实测的各镜头视频轨时长，累加得到，而不是
    timing.json 声明的时长，两者可能有编码器帧对齐级别的微小差异）决定，不做
    逐词/逐 beat 对齐（不引入新的字幕对齐算法，见计划范围说明）。

    本机 ffmpeg 编译时没有 drawtext/subtitles 滤镜（无 libass/freetype），改用
    Pillow 画字幕 PNG，再用 `overlay` 滤镜按时间窗口叠加。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        inputs: list[str] = ["-i", str(video_path)]
        filter_parts: list[str] = []
        prev_label = "0:v"
        offset = 0.0
        overlay_index = 0

        for plan, duration in zip(plans, scene_durations, strict=True):
            start, end = offset, offset + duration
            offset = end
            text = plan.narration.strip()
            if not text:
                continue

            overlay_index += 1
            image_path = tmp / f"sub_{overlay_index}.png"
            _render_subtitle_png(text, resolution, image_path)
            inputs.extend(["-loop", "1", "-i", str(image_path)])
            out_label = f"v{overlay_index}"
            filter_parts.append(
                f"[{prev_label}][{overlay_index}:v]"
                f"overlay=enable='between(t,{start:.3f},{end:.3f})'[{out_label}]"
            )
            prev_label = out_label

        if not filter_parts:
            shutil.copyfile(video_path, output_path)
            return

        total_duration = await probe_duration_seconds(str(video_path))
        await _run_subprocess(
            [
                "ffmpeg",
                "-y",
                *inputs,
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                f"[{prev_label}]",
                "-map",
                "0:a?",
                "-t",
                f"{total_duration:.3f}",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-c:a",
                "copy",
                str(output_path),
            ],
            error_prefix="叠加字幕失败",
        )


async def run_once(
    engine: Engine,
    blobs: BlobStore,
    *,
    data_dir: Path,
    render_engine: RenderEngine | None = None,
    resolution: tuple[int, int] = _DEFAULT_RESOLUTION,
    fps: int = _DEFAULT_FPS,
    heartbeat_timeout_seconds: float = _HEARTBEAT_TIMEOUT_SECONDS,
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
        clip_paths: list[Path] = []
        scene_durations: list[float] = []
        total = len(plans)
        for index, plan in enumerate(plans):
            heartbeat(engine, job.id)
            clip_path = await _render_and_cache_scene(
                engine_instance, workdir, plan, resolution=resolution, fps=fps
            )
            duration = await probe_duration_seconds(str(clip_path))
            clip_paths.append(clip_path)
            scene_durations.append(duration)
            update_progress(engine, job.id, (index + 1) / total)
            heartbeat(engine, job.id)
            logger.info("[worker] 镜头 %s 渲染完成（%.2fs）", plan.scene_id, duration)

        output_dir = workdir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / "final.mp4"

        concatenated = await _concat_clips(clip_paths, workdir)
        await _burn_subtitles(
            concatenated, plans, scene_durations, final_path, resolution=resolution
        )
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
