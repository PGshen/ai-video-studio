"""worker 进程入口：成片渲染任务循环（M2 T5，design §5.3/§10）。

独立进程，和 api 进程共用 `data/studio.db`、`data/blobs/`、`data/projects/<id>/`。
主循环：`run_forever` 反复调用 `run_once`；`run_once` 是单次迭代（方便测试），
流程是 reap 过期心跳 → 领取一条 `final_render` 任务 → 交给 HTML 引擎渲染
（`worker_html.run_html_job`）→ `complete`/`fail`。成片不叠字幕（ADR 0016）。

Manim 引擎已下线（ADR 0027）：老 manim 项目（设置里 `engine` 不是 `html`）的任务直接失败，
给出可读原因。

`worker` 不依赖 `agent`/`stages`/`api`/`main`（ARCHITECTURE §2 依赖表）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from studio.config import get_settings
from studio.db.engine import make_engine, migrate
from studio.db.repo.projects import get_project
from studio.jobs import claim_next, complete, fail, heartbeat, reap_stale_running
from studio.worker_html import HtmlBackend, HtmlJobError, real_backend, run_html_job
from studio.workspace import BlobStore, project_dir

logger = logging.getLogger(__name__)

_JOB_TYPE = "final_render"
_DEFAULT_FPS = 30
_HEARTBEAT_TIMEOUT_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 2.0
MANIM_RETIRED_ERROR = "Manim 动画已下线，老项目不能再渲染成片"


async def run_once(
    engine: Engine,
    blobs: BlobStore,
    *,
    data_dir: Path,
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
    if project is None or project.settings.get("engine") != "html":
        error = MANIM_RETIRED_ERROR if project is not None else f"项目不存在：{job.project_id}"
        logger.warning("[worker] 任务 %s 失败：%s", job.id, error)
        fail(engine, job.id, error=error)
        return True
    narration, music_source = _timeline_flags(project.settings)
    await _run_html(
        engine,
        blobs,
        job.id,
        job.project_id,
        data_dir,
        fps,
        html_backend,
        narration,
        music_source,
    )
    return True


def _timeline_flags(settings: Mapping[str, Any]) -> tuple[bool, str]:
    """项目设置里的 (有无旁白, 配乐来源)；字段缺失或取值不合法时按老项目处理（有旁白、无配乐）。

    `worker` 不依赖 `stages`，所以不复用 `kind_from_settings`，只取成片需要的两个值。
    """
    narration, music_source = settings.get("narration"), settings.get("music_source")
    if not isinstance(narration, bool) or music_source not in ("none", "synth", "import"):
        return True, "none"
    return narration, music_source


async def _run_html(
    engine: Engine,
    blobs: BlobStore,
    job_id: str,
    project_id: str,
    data_dir: Path,
    fps: int,
    backend: HtmlBackend | None,
    narration: bool,
    music_source: str,
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
            narration=narration,
            music_source=music_source,
        )
    except HtmlJobError as exc:
        logger.warning("[worker] 任务 %s 失败：%s", job_id, exc)
        fail(engine, job_id, error=str(exc))
        return
    except Exception as exc:
        # Playwright、ffmpeg、磁盘等没有列进具名错误的问题：任务必须落到 failed，否则它一直是
        # running，去重逻辑（TD-35）会让之后每次渲染都返回这条旧任务。
        logger.exception("[worker] 任务 %s 内部错误", job_id)
        fail(engine, job_id, error=f"成片渲染内部错误：{type(exc).__name__}: {exc}")
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
        try:
            claimed = await run_once(engine, blobs, data_dir=data_dir)
        except Exception:
            logger.exception("[worker] 迭代出错，稍后重试")
            claimed = False
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
