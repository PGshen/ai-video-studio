"""`stages.animation.prompt.md` 系统提示词（设计 §5.3、§5.5；计划 T9）。

轻量断言：只检查提示词包含关键章节/关键词，不做语义测试（T9 完成标准里
"人工通读一遍"这条才是内容质量的把关，测试只防止关键内容被误删）。
"""

from __future__ import annotations

from studio.stages.animation import STAGE as ANIMATION_STAGE
from studio.stages.animation.rules import ELEMENT_EXIT_RULES


def test_system_prompt_embeds_element_exit_rules_verbatim() -> None:
    prompt = ANIMATION_STAGE.system_prompt()
    assert ELEMENT_EXIT_RULES.strip() in prompt


def test_system_prompt_mentions_element_exit_keyword() -> None:
    assert "画面不重叠" in ANIMATION_STAGE.system_prompt()


def test_system_prompt_mentions_validate_scenes_tool() -> None:
    assert "validate_scenes" in ANIMATION_STAGE.system_prompt()


def test_system_prompt_mentions_render_preview_tool() -> None:
    assert "render_preview" in ANIMATION_STAGE.system_prompt()


def test_system_prompt_mentions_scene_merge_convention() -> None:
    prompt = ANIMATION_STAGE.system_prompt()
    assert "Scene" in prompt
    assert "合并" in prompt


def test_system_prompt_mentions_manim_version() -> None:
    assert "Manim Community v0.20.1" in ANIMATION_STAGE.system_prompt()


def test_system_prompt_mentions_style_component_experience() -> None:
    prompt = ANIMATION_STAGE.system_prompt()
    for keyword in ("布局骨架", "图标克制", "转场不留中间态", "角落堆放"):
        assert keyword in prompt


def test_element_exit_rules_constant_is_non_empty() -> None:
    assert "画面不重叠" in ELEMENT_EXIT_RULES
    assert ELEMENT_EXIT_RULES.strip() != ""
