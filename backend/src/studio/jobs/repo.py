"""`studio.jobs` 对外暴露的仓储函数：实现在 `studio.db.repo.jobs`。

这一层转发存在的原因是 ARCHITECTURE 规则 5（"只有 `db` 定义 ORM 模型；其他模块
只通过 `db.repo` 读写"）——`Job` 模型的直接读写要留在 `db.repo` 包里，`studio.jobs`
经由这个间接 import 拿到仓储函数，不直接依赖 `studio.db.models`。
"""

from __future__ import annotations

from studio.db.repo.jobs import (
    JobValue,
    claim_next,
    complete,
    create_job,
    fail,
    get_job,
    heartbeat,
    list_jobs,
    reap_stale_running,
    update_progress,
)

__all__ = [
    "JobValue",
    "claim_next",
    "complete",
    "create_job",
    "fail",
    "get_job",
    "heartbeat",
    "list_jobs",
    "reap_stale_running",
    "update_progress",
]
