"""`StageRegistry` 的最小单测（`StageDefinition` 协议本身通过
`tests/stages/test_placeholders.py` 的三个占位实现间接覆盖）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.agent.stage import StageRegistry
from studio.agent.tools import ToolSpec
from studio.workspace.scope import WriteScope


class _StubStage:
    name = "stub"

    def system_prompt(self) -> str:
        return "stub"

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return WriteScope(writable=[], tool_managed=[])

    def upstream_stages(self) -> list[str]:
        return []

    def artifact_dirs(self) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        return "stub"


class TestStageRegistry:
    def test_register_then_get_returns_same_instance(self) -> None:
        registry = StageRegistry()
        stage = _StubStage()

        registry.register(stage)

        assert registry.get("stub") is stage

    def test_get_unregistered_name_raises_key_error(self) -> None:
        registry = StageRegistry()

        with pytest.raises(KeyError):
            registry.get("missing")
