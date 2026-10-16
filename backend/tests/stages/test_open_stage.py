"""`stages.open`：完全自由模式的单阶段（open-mode 设计 §4）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.agent.preamble import PreambleInputs, build_preamble
from studio.agent.stage import StageDefinition
from studio.stages.open import STAGE
from studio.workspace import WorkspaceDiff
from studio.workspace.scope import is_writable


def test_satisfies_the_stage_protocol() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "open"
    assert STAGE.allow_web is True
    assert STAGE.exec_network is True
    assert STAGE.workspaceless is False
    assert STAGE.reads() == []
    assert STAGE.artifact_dirs() == []


def test_uses_the_runtime_default_prompt() -> None:
    assert STAGE.system_prompt() is None


def test_tools_are_only_tts_plus_the_web_fallback() -> None:
    """`web_search`/`fetch_url` 只在 `tools` 联网模式下留下（native 模式由 runner 滤掉）。"""
    tools = STAGE.tools()
    assert {tool.name for tool in tools} == {"tts", "web_search", "fetch_url"}
    assert {tool.name for tool in tools if not tool.web} == {"tts"}
    assert all("open" in tool.stages for tool in tools)


@pytest.mark.parametrize(
    "path",
    ["style/STYLE.md", "project.md", "a/b/c.mp4", "index.html", "notes/x.md", "music/music.wav"],
)
def test_the_whole_workspace_is_writable(path: str) -> None:
    assert is_writable(STAGE.write_scope(), path)


@pytest.mark.parametrize(
    "path", ["uploads/x.png", ".cache/x", "upstream/topic/brief.md", "output/final.mp4"]
)
def test_system_dirs_and_uploads_are_not_writable(path: str) -> None:
    assert not is_writable(STAGE.write_scope(), path)


def test_has_no_status_and_no_finalize_blockers(tmp_path: Path) -> None:
    (tmp_path / "anything.txt").write_text("x", encoding="utf-8")
    assert STAGE.status_summary(tmp_path) == ""
    assert STAGE.finalize_blockers(tmp_path) == []


def test_prepare_turn_writes_nothing(tmp_path: Path) -> None:
    STAGE.prepare_turn(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_preamble_only_carries_user_edits(tmp_path: Path) -> None:
    edits = WorkspaceDiff(added=["project.md"], removed=[], modified=[])
    inputs = PreambleInputs(
        user_edits=edits,
        status_summary=STAGE.status_summary(tmp_path),
        handoff_files=STAGE.artifact_dirs(),
    )

    text = build_preamble(inputs)

    assert "## 用户手动修改的文件" in text
    assert "## 当前产物状态" not in text
    assert "## 会话交接" not in text
