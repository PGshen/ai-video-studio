"""无旁白、配乐与画面一起做的阶段共用的流程件：每轮准备、定稿条件、状态摘要。

`produce`（短片、MV 的多阶段版）与 `free_produce`（自由短片、自由 MV）共用
（free-mode 设计 §4.2；各阶段之间互不 import）。
"""

from studio.stages.common.produce_flow.blockers import finalize_blockers, status_summary
from studio.stages.common.produce_flow.prepare import prepare_turn

__all__ = ["finalize_blockers", "prepare_turn", "status_summary"]
