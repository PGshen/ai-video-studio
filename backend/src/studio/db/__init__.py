"""SQLite 连接、ORM 模型与迁移。

只有本模块定义 ORM 模型（ARCHITECTURE §2 规则 5）；其他模块通过
`studio.db.repo` 下的仓储函数读写数据，得到的是 dataclass/Pydantic 值对象，
不会拿到 ORM 实例。
"""

from __future__ import annotations

from studio.db.engine import make_engine, migrate, session_scope

__all__ = ["make_engine", "migrate", "session_scope"]
