"""`ConceptStage`：协议值、可写范围、定稿条件、提示词（子项目 3 设计 §6.1）。"""

from __future__ import annotations

from pathlib import Path

from studio.agent.stage import StageDefinition
from studio.stages.concept import STAGE
from studio.stages.concept.check_concept import SECTIONS
from studio.workspace.scope import is_writable


def _write_brief(workdir: Path, text: str) -> None:
    (workdir / "concept").mkdir(exist_ok=True)
    (workdir / "concept" / "brief.md").write_text(text, encoding="utf-8")


def test_stage_protocol_values() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "concept" and STAGE.allow_web is True and STAGE.workspaceless is False
    assert STAGE.reads() == [] and STAGE.artifact_dirs() == ["concept", "music"]
    scope = STAGE.write_scope()
    assert is_writable(scope, "concept/brief.md") is True
    assert is_writable(scope, "beatsheet/beatsheet.json") is False
    assert is_writable(scope, "music/compose.py") is False


def test_song_files_are_tool_managed_not_agent_writable() -> None:
    scope = STAGE.write_scope()
    for relpath in (
        "music/source.mp3",
        "music/source.wav",
        "music/analysis.json",
        "music/analysis.png",
        "music/lyrics.lrc",
    ):
        assert is_writable(scope, relpath) is False
        assert relpath in scope.tool_managed or any(
            pattern == relpath for pattern in scope.tool_managed
        )


def test_the_song_analysis_tool_is_available_for_song_projects() -> None:
    assert "analyze_music" in {tool.name for tool in STAGE.tools()}


def test_finalize_is_blocked_by_check_errors_only(tmp_path: Path) -> None:
    assert STAGE.finalize_blockers(tmp_path)  # no brief yet
    full = "\n".join(f"## {name}\n\n内容。\n" for name in SECTIONS)
    full = full.replace("## 目标时长\n\n内容。", "## 目标时长\n\n20 秒")
    _write_brief(tmp_path, full)
    assert STAGE.finalize_blockers(tmp_path) == []


def test_status_summary_counts_sections(tmp_path: Path) -> None:
    _write_brief(tmp_path, "## 主题\n\n内容\n\n## 视觉母题\n\n内容\n")
    assert "2/8" in STAGE.status_summary(tmp_path)


def test_prompt_states_the_contract() -> None:
    prompt = STAGE.system_prompt()
    for needle in ("concept/brief.md", "目标时长", "check_concept", "视觉母题", "能量走向"):
        assert needle in prompt
    for name in SECTIONS:
        assert name in prompt


def test_prompt_covers_hard_requirements_and_song_projects() -> None:
    prompt = STAGE.system_prompt()
    for needle in ("硬性要求", "analyze_music", "music/source.", "配乐与动画"):
        assert needle in prompt
    for gone in ("节拍脚本", "beatsheet"):
        assert gone not in prompt


def test_the_prompt_explains_the_optional_lyrics_and_the_imagery_chapter() -> None:
    prompt = STAGE.system_prompt()
    for needle in ("music/lyrics.lrc", "歌词意象", "逐字引用", "不要自己编歌词", "check_concept"):
        assert needle in prompt, needle
