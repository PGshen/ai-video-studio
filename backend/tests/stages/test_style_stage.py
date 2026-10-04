"""风格对话阶段（计划 style-library T9）：写范围、`validate_style` 工具、提示词要点。"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.agent.fake import Write, default_fake_script
from studio.agent.stage import StageDefinition
from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.style import STAGE, VALIDATE_STYLE_TOOL
from studio.workspace.scope import is_writable

ENTRY = "---\nname: 暖纸双色\ndescription: 暖色双色风格\n---\n\n先读 `references/color.md`。\n"


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id=None, stage="style", workdir=workdir, record_tool_write=lambda *_: None
    )


class TestDefinition:
    def test_is_a_workspaceless_stage_without_web_or_upstream(self) -> None:
        assert isinstance(STAGE, StageDefinition)
        assert STAGE.name == "style"
        assert STAGE.workspaceless is True  # no project; the subject is the style
        assert STAGE.allow_web is False
        assert STAGE.reads() == []
        assert STAGE.artifact_dirs() == []
        assert STAGE.finalize_blockers(Path(".")) == []

    def test_only_the_style_layout_is_writable(self) -> None:
        scope = STAGE.write_scope()
        for path in ("STYLE.md", "references/color.md", "exemplars/e1.json", "exemplars/x.md"):
            assert is_writable(scope, path), path
        for path in ("notes.md", "style/STYLE.md", "upstream/x.md", "topic/brief.md", "other/a.md"):
            assert not is_writable(scope, path), path

    def test_the_fake_runtimes_default_script_can_edit_the_draft(self) -> None:
        """端到端演示（`enable_fake_runtime`）：默认脚本在第一个可写目录里写 `fake-note.md`，
        对风格阶段必须落在 `references/` 里，而不是被越界拦截。"""
        script = default_fake_script(STAGE.write_scope(), "你好")
        writes = [step for step in script if isinstance(step, Write)]
        assert [w.path for w in writes] == ["references/fake-note.md"]
        assert is_writable(STAGE.write_scope(), writes[0].path)

    def test_the_only_tool_is_validate_style_and_it_is_for_this_stage_only(self) -> None:
        assert [t.name for t in STAGE.tools()] == ["validate_style"]
        assert VALIDATE_STYLE_TOOL.stages == {"style"}
        assert not VALIDATE_STYLE_TOOL.web


class TestPrompt:
    @pytest.fixture
    def prompt(self) -> str:
        return STAGE.system_prompt()

    def test_explains_the_directory_layout(self, prompt: str) -> None:
        for needle in ("STYLE.md", "references/", "exemplars/", "草稿"):
            assert needle in prompt, needle

    def test_explains_the_frontmatter_fields(self, prompt: str) -> None:
        for needle in ("frontmatter", "name", "description", "category"):
            assert needle in prompt, needle

    def test_requires_the_entry_to_index_every_file_with_when_to_read(self, prompt: str) -> None:
        assert "什么时候读" in prompt or "什么时候读取" in prompt
        for stage in ("选题", "叙事", "动画"):
            assert stage in prompt

    def test_states_the_file_rules_and_the_self_check(self, prompt: str) -> None:
        for needle in ("validate_style", ".json", ".md", "文件名"):
            assert needle in prompt, needle

    def test_tells_the_agent_not_to_touch_anything_outside_the_draft(self, prompt: str) -> None:
        assert "只能" in prompt and "之外" in prompt


class TestValidateStyleTool:
    async def test_passes_for_a_valid_draft(self, tmp_path: Path) -> None:
        (tmp_path / "references").mkdir()
        (tmp_path / "STYLE.md").write_text(ENTRY, encoding="utf-8")
        (tmp_path / "references" / "color.md").write_text("主色", encoding="utf-8")

        result = await invoke_tool(VALIDATE_STYLE_TOOL, _ctx(tmp_path), {})

        assert not result.is_error
        assert "通过" in result.text

    async def test_lists_every_problem_at_once(self, tmp_path: Path) -> None:
        (tmp_path / "STYLE.md").write_text(
            "没有 frontmatter，还引用了 `references/gone.md`", "utf-8"
        )
        (tmp_path / "notes.md").write_text("多余的顶层文件", encoding="utf-8")

        result = await invoke_tool(VALIDATE_STYLE_TOOL, _ctx(tmp_path), {})

        assert result.is_error
        assert "frontmatter" in result.text
        assert "notes.md" in result.text
        assert "references/gone.md" in result.text

    async def test_reports_symlinks_and_non_utf8_files(self, tmp_path: Path) -> None:
        (tmp_path / "references").mkdir()
        (tmp_path / "STYLE.md").write_text(
            ENTRY.replace("先读 `references/color.md`。", ""), "utf-8"
        )
        (tmp_path / "references" / "link.md").symlink_to(tmp_path / "STYLE.md")
        (tmp_path / "references" / "bin.md").write_bytes(b"\xff\xfe\x00")

        result = await invoke_tool(VALIDATE_STYLE_TOOL, _ctx(tmp_path), {})

        assert result.is_error
        assert "link.md" in result.text and "bin.md" in result.text

    async def test_a_missing_directory_is_an_error_not_a_crash(self, tmp_path: Path) -> None:
        result = await invoke_tool(VALIDATE_STYLE_TOOL, _ctx(tmp_path / "gone"), {})
        assert result.is_error
