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


def test_system_prompt_tells_the_agent_which_style_files_to_read_and_when() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    assert "style/STYLE.md" in prompt
    assert "style/references/narrative-blueprint.md" in prompt
    assert "style/exemplars/" in prompt
    assert "动笔" in prompt


def test_system_prompt_handles_missing_style_files_and_old_field_names() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    assert "这些文件不存在" in prompt
    # 导入的旧风格可能沿用旧字段名，产物字段必须以本提示词为准
    for old_field in ("scene_index", "beat_index", "estimated_duration_seconds"):
        assert old_field in prompt
    assert "以本提示词为准" in prompt


def test_system_prompt_lists_every_transition_value() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    for value in ("continue", "transform", "reveal", "replace", "exit"):
        assert value in prompt


def test_system_prompt_mentions_tool_managed_files() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    assert "timing.json" in prompt
    assert "scene_ids" in prompt


def test_system_prompt_tells_the_agent_not_to_draft_the_script_twice() -> None:
    prompt = NARRATIVE_STAGE.system_prompt()
    assert "不要在思考里起草" in prompt
    assert "直接写进 `narrative/narrative.json`" in prompt
