"""三个阶段占位定义（设计 §4.3）：只验证可写范围、上游、产物目录这些
`StageDefinition` 协议的关键值——业务工具、产物 schema 在各阶段任务里实现。
"""

from __future__ import annotations

from pathlib import Path

from studio.stages.animation import STAGE as animation_stage
from studio.stages.narrative import STAGE as narrative_stage
from studio.stages.topic import STAGE as topic_stage
from studio.workspace.scope import is_writable


class TestTopicStage:
    def test_write_scope_matches_design(self) -> None:
        scope = topic_stage.write_scope()
        assert is_writable(scope, "topic/brief.md") is True
        assert is_writable(scope, "style/STYLE.md") is False

    def test_upstream_and_artifact_dirs(self) -> None:
        assert topic_stage.upstream_stages() == []
        assert topic_stage.artifact_dirs() == ["topic"]

    def test_no_business_tools_in_m1(self) -> None:
        assert topic_stage.tools() == []

    def test_web_tools_disabled_until_domain_policy(self) -> None:
        # TD-1: no stage gets web tools until M4 adds a domain allowlist.
        assert topic_stage.allow_web is False

    def test_system_prompt_is_non_empty(self) -> None:
        assert topic_stage.system_prompt().strip() != ""

    def test_status_summary_on_empty_workdir(self, tmp_path: Path) -> None:
        assert isinstance(topic_stage.status_summary(tmp_path), str)


class TestNarrativeStage:
    def test_write_scope_matches_design(self) -> None:
        scope = narrative_stage.write_scope()
        assert is_writable(scope, "narrative/narrative.json") is True
        assert is_writable(scope, "narrative/timing.json") is False

    def test_upstream_and_artifact_dirs(self) -> None:
        assert narrative_stage.upstream_stages() == ["topic"]
        assert narrative_stage.artifact_dirs() == ["narrative"]

    def test_web_tools_not_allowed(self) -> None:
        assert narrative_stage.allow_web is False

    def test_tools_are_validate_synthesize_and_suggest(self) -> None:
        names = {tool.name for tool in narrative_stage.tools()}
        assert names == {"validate_narrative", "synthesize_tts", "suggest_upstream_change"}


class TestAnimationStage:
    def test_write_scope_matches_design(self) -> None:
        scope = animation_stage.write_scope()
        assert is_writable(scope, "animation/scenes/s-hook.py") is True
        assert is_writable(scope, "narrative/narrative.json") is False

    def test_upstream_and_artifact_dirs(self) -> None:
        assert animation_stage.upstream_stages() == ["narrative"]
        assert animation_stage.artifact_dirs() == ["animation/scenes"]

    def test_web_tools_not_allowed(self) -> None:
        assert animation_stage.allow_web is False

    def test_tools_include_suggest_upstream_change(self) -> None:
        # TD-32: `suggest_upstream_change` 现在跟其它业务工具一起是模块级常量，
        # 不再需要单独给阶段实例注入 Engine 才能出现在 tools() 里。
        names = {tool.name for tool in animation_stage.tools()}
        assert names == {"validate_scenes", "render_preview", "suggest_upstream_change"}
