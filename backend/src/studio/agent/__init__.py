"""运行时无关的 agent 抽象：事件、工具、运行时协议、阶段协议、会话总线、
`FakeRuntime`（设计 §4）。

`agent` 不 import `stages`（ARCHITECTURE §2 规则 2）：`stage.StageDefinition`
是具体阶段和这个模块之间的协议边界。
"""

from __future__ import annotations

from studio.agent.fake import register_fake

__all__ = ["register_fake"]
