"""设计 §4.4 第 8 步：进程重启后恢复上次遗留的 `running`/`queued` turn。

拆自 `runner.py`（TD-15）。`recover_on_startup` 是 `TurnRunner` 的公开方法之一
（M1 启动流程会调用它），这里只是把实现移出来，行为不变。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from studio.db.repo import turns as turns_repo
from studio.db.repo.sessions import SessionValue, get_session
from studio.db.repo.snapshots import get_snapshot
from studio.workspace import create_snapshot, guard, project_dir, scan

if TYPE_CHECKING:
    from studio.agent.runner import TurnRunner

logger = logging.getLogger(__name__)


def recover_on_startup(runner: TurnRunner) -> None:
    """上次进程遗留的 `running`/`queued` turn → `interrupted`。

    `running` 的 turn 先做一份 `partial` 快照（产物永远不丢，§7），再改状态；
    没有越界检查（本轮工具写入记录已随进程丢失）。`queued` 的 turn 从未
    开始，排队信息只在内存里，同样标记为 `interrupted`，否则会话会一直"忙"。
    """
    for turn in turns_repo.list_unfinished_turns(runner._engine):
        try:
            _recover_turn(runner, turn)
        except Exception:
            logger.exception("恢复 turn %s 失败，继续处理其他 turn", turn.id)


def _recover_turn(runner: TurnRunner, turn: turns_repo.TurnValue) -> None:
    end_snapshot_id: str | None = None
    session = get_session(runner._engine, turn.session_id)
    if turn.status == "running" and session is not None and session.project_id:
        workdir = project_dir(runner._settings.data_dir, session.project_id)
        _guard_recovered_turn(runner, turn, session, workdir)
        try:
            snapshot = create_snapshot(
                runner._engine, runner._blobs, session.project_id, "partial", turn.id
            )
            end_snapshot_id = snapshot.id
        except Exception:
            logger.exception("turn %s 恢复时快照失败", turn.id)
    turns_repo.interrupt_turn(runner._engine, turn.id, end_snapshot_id=end_snapshot_id)


def _guard_recovered_turn(
    runner: TurnRunner, turn: turns_repo.TurnValue, session: SessionValue, workdir: Path
) -> None:
    """TD-7：`running` turn 恢复时按该阶段的 `write_scope` 做一次越界还原。

    本轮的工具写入记录随进程丢失，`tool_writes` 传空字典——guard 因此只能
    按可写范围区分，不能像正常收尾那样保留"工具管理但范围外"的文件；
    这对 M1 已有的工具管理文件（都在各阶段自己的可写范围内）没有影响。
    起始快照或阶段未注册时跳过，只记日志，不阻止恢复。
    """
    if turn.start_snapshot_id is None:
        logger.warning("turn %s 没有起始快照，恢复时跳过越界检查", turn.id)
        return
    start = get_snapshot(runner._engine, turn.start_snapshot_id)
    if start is None:
        logger.warning(
            "turn %s 的起始快照 %s 不存在，恢复时跳过越界检查",
            turn.id,
            turn.start_snapshot_id,
        )
        return
    try:
        stage = runner._registry.get(session.stage)
    except KeyError:
        logger.warning("会话 %s 的阶段 %s 未注册，恢复时跳过越界检查", session.id, session.stage)
        return
    try:
        guard(workdir, start.manifest, scan(workdir), stage.write_scope(), runner._blobs, {})
    except Exception:
        logger.exception("turn %s 恢复时越界检查失败", turn.id)
