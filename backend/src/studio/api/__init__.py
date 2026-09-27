"""HTTP 路由（设计 §2.1；ARCHITECTURE §2）：组装层，可以依赖所有下层模块。

只有 `studio.main` 允许 import 这个包（控制者裁定 1，import-linter 契约见
`pyproject.toml`）。子模块划分：`deps`（从 `app.state` 取出单例）、`schemas`
（请求/响应模型）、`projects`/`files`/`snapshots`/`profiles`（各自的
`APIRouter`）。
"""

from __future__ import annotations
