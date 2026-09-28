"""一轮结束的收尾（设计 §4.4、§7）：越界检查 → 快照 → 写 turn 状态 → 发布
`turn_status`。任何结束方式（完成、失败、取消、超预算、异常、task 被取消）都走
`finish`：**先快照、后改状态**。

拆自 `runner.py`（TD-15）。`finish_turn_row` 单独导出，因为 `TurnRunner.cancel`
（排队中直接取消，不经过 `finish`）也要用它写最终状态。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from studio.agent import stage_flow
from studio.agent.preamble import GUARD_RESTORED_NOTICE
from studio.agent.turn_state import _Job, _State
from studio.db.repo import turns as turns_repo
from studio.workspace import (
    create_snapshot,
    guard,
    materialize_upstream,
    project_dir,
    scan,
    upstream_drift,
)

if TYPE_CHECKING:
    from studio.agent.runner import TurnRunner

logger = logging.getLogger(__name__)


def finish(runner: TurnRunner, job: _Job, state: _State) -> None:
    """越界检查 → 快照 → 写 turn 状态 → 发布 `turn_status`。每一步单独兜底。"""
    status, error = state.final_status()
    if job.shutdown and status == "cancelled":
        status = "interrupted"
    workdir = project_dir(runner._settings.data_dir, job.project_id)
    try:
        restored: list[str] = []
        if state.before is not None:
            report = guard(
                workdir,
                state.before,
                scan(workdir),
                job.stage.write_scope(),
                runner._blobs,
                state.tool_writes,
            )
            restored = report.restored
        if state.sources is not None:
            # Agent changes to the read-only copy are dropped and reported (R5).
            restored += upstream_drift(workdir, state.sources)
            materialize_upstream(workdir, runner._blobs, state.sources)
        if restored:
            runner._persist(job, "notice", {"kind": GUARD_RESTORED_NOTICE, "paths": restored})
            runner._publish(job, "workspace_changed", {"paths": restored})
    except Exception as exc:
        logger.exception("turn %s 越界检查失败", job.turn_id)
        status, error = "failed", error or f"越界检查失败：{exc}"

    if status == "failed":
        runner._safe_persist(job, "error", {"message": error or "未知错误"})

    end_snapshot_id: str | None = None
    try:
        reason = "partial" if status in ("failed", "interrupted") else "turn"
        snapshot = create_snapshot(
            runner._engine, runner._blobs, job.project_id, reason, job.turn_id
        )
        end_snapshot_id = snapshot.id
        runner._persist(
            job,
            "snapshot",
            {
                "snapshot_id": snapshot.id,
                "reason": snapshot.reason,
                "created": snapshot.created,
            },
        )
    except Exception as exc:
        logger.exception("turn %s 结束快照失败", job.turn_id)
        status, error = "failed", error or f"结束快照失败：{exc}"

    usage: dict[str, Any] = {
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "steps": state.steps,
    }
    finish_turn_row(
        runner,
        job,
        status=status,
        end_snapshot_id=end_snapshot_id,
        usage=usage,
        cost_usd=None if state.cost_unpriced else state.cost_usd,
        error=error,
        resume_ref=state.end.resume_ref if state.end is not None else None,
    )
    if status == "done":
        try:
            stage_flow.after_turn_done(
                runner._engine, job.project_id, job.stage.name, state.upstream_ids
            )
        except Exception:
            logger.exception("turn %s 更新阶段状态失败", job.turn_id)
    runner._publish_status(job, status, error)


def finish_turn_row(runner: TurnRunner, job: _Job, **fields: Any) -> None:
    """写 turn 最终状态，失败时重试一次（例如 SQLite 繁忙）；再失败只记日志。

    否则内存里的并发名额已释放，数据库却一直是 `running`，会话在重启前
    都会返回"忙"。
    """
    for attempt in (1, 2):
        try:
            turns_repo.finish_turn(runner._engine, job.turn_id, **fields)
            return
        except Exception:
            logger.exception("turn %s 写入最终状态失败（第 %d 次）", job.turn_id, attempt)
