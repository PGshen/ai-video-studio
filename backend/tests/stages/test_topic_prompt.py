"""选题阶段提示词的轻量断言（计划 M4 T6）。"""

from __future__ import annotations

from studio.stages.topic import STAGE
from studio.stages.topic.brief import SECTIONS


def test_prompt_lists_every_section() -> None:
    prompt = STAGE.system_prompt()
    for name in SECTIONS:
        assert name in prompt


def test_prompt_only_asks_for_the_style_entry_file() -> None:
    prompt = STAGE.system_prompt()
    assert "style/STYLE.md" in prompt
    assert "其余文件不用读" in prompt
    assert "style/references/" not in prompt
    assert "style/exemplars/" not in prompt


def test_prompt_documents_fact_format_and_tools() -> None:
    prompt = STAGE.system_prompt()
    for keyword in ("出处", "把握程度", "check_brief", "topic/notes", "idea-card.md"):
        assert keyword in prompt


def test_prompt_forbids_inventing_sources_and_finalizing() -> None:
    prompt = STAGE.system_prompt()
    assert "不能凭记忆编造" in prompt
    assert "不要自己定稿" in prompt


def test_prompt_is_mode_agnostic_about_web_tools() -> None:
    prompt = STAGE.system_prompt()
    assert "联网" in prompt
    assert "web_search" not in prompt and "WebSearch" not in prompt
