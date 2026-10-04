"""`StageRegistry` 的最小单测（`StageDefinition` 协议本身通过
`tests/stages/test_placeholders.py` 的三个占位实现间接覆盖）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.agent.stage import StageRegistry, upstream_of
from studio.agent.tools import ToolSpec
from studio.workspace.scope import WriteScope


class _StubStage:
    name = "stub"
    allow_web = False
    workspaceless = False

    def __init__(self, name: str = "stub", reads: list[str] | None = None) -> None:
        self.name = name
        self._reads = reads or []

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def system_prompt(self) -> str:
        return "stub"

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return WriteScope(writable=[], tool_managed=[])

    def reads(self) -> list[str]:
        return list(self._reads)

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


_READS = {
    "topic": [],
    "concept": [],
    "narrative": ["topic"],
    "beatsheet": ["concept", "music"],
    "music": ["concept", "narrative", "beatsheet"],
    "animation": ["narrative"],
    "animation_html": ["narrative", "beatsheet", "music"],
}


def _registry() -> StageRegistry:
    registry = StageRegistry()
    for name, reads in _READS.items():
        registry.register(_StubStage(name, reads))
    return registry


class TestUpstreamOf:
    def test_has(self) -> None:
        registry = _registry()
        assert registry.has("music") is True
        assert registry.has("nope") is False

    def test_motion_reel_pipeline(self) -> None:
        pipeline = ["concept", "beatsheet", "music", "animation_html"]
        registry = _registry()
        assert upstream_of(pipeline, registry, "music") == ["concept", "beatsheet"]
        assert upstream_of(pipeline, registry, "animation_html") == ["beatsheet", "music"]

    def test_music_video_pipeline(self) -> None:
        pipeline = ["concept", "music", "beatsheet", "animation_html"]
        registry = _registry()
        assert upstream_of(pipeline, registry, "music") == ["concept"]
        assert upstream_of(pipeline, registry, "beatsheet") == ["concept", "music"]
        assert upstream_of(pipeline, registry, "animation_html") == ["music", "beatsheet"]

    def test_explainer_with_music(self) -> None:
        pipeline = ["topic", "narrative", "music", "animation"]
        registry = _registry()
        assert upstream_of(pipeline, registry, "music") == ["narrative"]
        assert upstream_of(pipeline, registry, "animation") == ["narrative"]

    def test_legacy_pipeline(self) -> None:
        pipeline = ["topic", "narrative", "animation"]
        registry = _registry()
        assert upstream_of(pipeline, registry, "topic") == []
        assert upstream_of(pipeline, registry, "narrative") == ["topic"]
        assert upstream_of(pipeline, registry, "animation") == ["narrative"]

    def test_stage_outside_pipeline_or_unregistered(self) -> None:
        registry = _registry()
        assert upstream_of(["topic", "narrative"], registry, "animation") == []
        assert upstream_of(["topic", "ghost"], registry, "ghost") == []
