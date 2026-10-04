"""三个阶段占位定义（设计 §4.3）：只验证可写范围、上游、产物目录这些
`StageDefinition` 协议的关键值——业务工具、产物 schema 在各阶段任务里实现。
"""

from __future__ import annotations

from pathlib import Path

from studio.stages.animation import STAGE as animation_stage
from studio.stages.brainstorm import STAGE as brainstorm_stage
from studio.stages.narrative import STAGE as narrative_stage
from studio.stages.topic import STAGE as topic_stage
from studio.workspace.scope import is_writable


class TestTopicStage:
    def test_write_scope_matches_design(self) -> None:
        scope = topic_stage.write_scope()
        assert is_writable(scope, "topic/brief.md") is True
        assert is_writable(scope, "style/STYLE.md") is False

    def test_upstream_and_artifact_dirs(self) -> None:
        assert topic_stage.reads() == []
        assert topic_stage.artifact_dirs() == ["topic"]

    def test_web_is_allowed_and_tools_include_web_tools(self) -> None:
        # ADR 0010: web use is a stage capability, the mode (STUDIO_WEB_MODE) picks the
        # implementation; the runner filters the self-built tools out in native mode.
        assert topic_stage.allow_web is True
        assert {"web_search", "fetch_url"} <= {t.name for t in topic_stage.tools()}

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
        assert narrative_stage.reads() == ["topic"]
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
        assert animation_stage.reads() == ["narrative"]
        assert animation_stage.artifact_dirs() == ["animation/scenes"]

    def test_web_tools_not_allowed(self) -> None:
        assert animation_stage.allow_web is False

    def test_tools_include_suggest_upstream_change(self) -> None:
        # TD-32: `suggest_upstream_change` 现在跟其它业务工具一起是模块级常量，
        # 不再需要单独给阶段实例注入 Engine 才能出现在 tools() 里。
        names = {tool.name for tool in animation_stage.tools()}
        assert names == {"validate_scenes", "render_preview", "suggest_upstream_change"}


class TestBrainstormStage:
    def test_has_no_workspace(self) -> None:
        scope = brainstorm_stage.write_scope()
        assert scope.writable == [] and scope.tool_managed == []
        assert brainstorm_stage.reads() == []
        assert brainstorm_stage.artifact_dirs() == []

    def test_prompt_and_summary(self, tmp_path: Path) -> None:
        assert brainstorm_stage.name == "brainstorm"
        assert brainstorm_stage.system_prompt().strip() != ""
        assert isinstance(brainstorm_stage.status_summary(tmp_path), str)
