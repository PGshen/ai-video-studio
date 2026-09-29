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
    remove_scratch,
    scan,
    upstream_drift,
)

if TYPE_CHECKING:
    from studio.agent.runner import TurnRunner

logger = logging.getLogger(__name__)


def finish(runner: TurnRunner, job: _Job, state: _State) -> None:
    """越界检查 → 快照 → 写 turn 状态 → 发布 `turn_status`。每一步单独兜底。

    无项目会话（`job.project_id is None`，头脑风暴）没有工作区：跳过越界检查、快照和
    阶段状态更新，其余（`error` 事件、用量、写 turn 状态、发布状态）不变。
    """
    status, error = state.final_status()
    if job.shutdown and status == "cancelled":
        status = "interrupted"
    project_id = job.project_id
    if project_id is not None:
        status, error = _guard_workspace(runner, job, state, project_id, status, error)
    else:
        # 无项目会话的 scratch 只是这一轮的 cwd，用完即删（下一轮开始时还会重建）。
        remove_scratch(runner._settings.data_dir, job.session.id)

    if status == "failed":
        runner._safe_persist(job, "error", {"message": error or "未知错误"})

    end_snapshot_id: str | None = None
    if project_id is not None:
        status, error, end_snapshot_id = _snapshot_workspace(runner, job, project_id, status, error)

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
    if status == "done" and project_id is not None:
        try:
            stage_flow.after_turn_done(
                runner._engine, project_id, job.stage.name, state.upstream_ids
            )
        except Exception:
            logger.exception("turn %s 更新阶段状态失败", job.turn_id)
    runner._publish_status(job, status, error)


def _guard_workspace(
    runner: TurnRunner,
    job: _Job,
    state: _State,
    project_id: str,
    status: str,
    error: str | None,
) -> tuple[str, str | None]:
    workdir = project_dir(runner._settings.data_dir, project_id)
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
        return "failed", error or f"越界检查失败：{exc}"
    return status, error


def _snapshot_workspace(
    runner: TurnRunner, job: _Job, project_id: str, status: str, error: str | None
) -> tuple[str, str | None, str | None]:
    snapshot_id: str | None = None
    try:
        reason = "partial" if status in ("failed", "interrupted") else "turn"
        snapshot = create_snapshot(runner._engine, runner._blobs, project_id, reason, job.turn_id)
        snapshot_id = snapshot.id
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
        return "failed", error or f"结束快照失败：{exc}", snapshot_id
    return status, error, snapshot_id


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
