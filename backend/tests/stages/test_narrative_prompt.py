"""`stages.narrative.prompt.md` 系统提示词（设计 §5.2、§5.5；计划 M3 T7）。

轻量断言：只检查提示词包含关键词，防止关键内容被误删；内容质量靠人工通读。
"""

from __future__ import annotations

from studio.stages.narrative import STAGE as NARRATIVE_STAGE


def test_system_prompt_mentions_all_three_tools() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    for tool in ("validate_narrative", "synthesize_tts", "suggest_upstream_change"):
        assert tool in prompt


def test_system_prompt_mentions_artifact_fields() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    for keyword in ("cue_text", "visual_action", "emphasis", "transition", "visual_intent"):
        assert keyword in prompt


def test_system_prompt_lists_every_transition_value() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    for value in ("continue", "transform", "reveal", "replace", "exit"):
        assert value in prompt


def test_system_prompt_mentions_tool_managed_files() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    assert "timing.json" in prompt
    assert "scene_ids" in prompt
