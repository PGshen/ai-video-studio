"""头脑风暴提示词的轻量断言（计划 M4 T4）：防止关键内容被误删，质量靠人工通读。"""

from __future__ import annotations

from studio.stages.brainstorm import STAGE


def test_prompt_mentions_tools_and_dedupe_first() -> None:
    prompt = STAGE.system_prompt()
    for tool in ("list_ideas", "create_idea", "update_idea"):
        assert tool in prompt
    assert prompt.index("list_ideas") < prompt.index("create_idea")


def test_prompt_explains_scores_and_counterintuitive_point() -> None:
    prompt = STAGE.system_prompt()
    for keyword in ("反直觉", "可论证", "可视化", "新鲜度", "1–5"):
        assert keyword in prompt


def test_prompt_is_mode_agnostic_about_web_tools() -> None:
    # 联网可能是自建工具也可能是原生工具（STUDIO_WEB_MODE），提示词不写死工具名。
    prompt = STAGE.system_prompt()
    assert "联网" in prompt
    assert "web_search" not in prompt and "WebSearch" not in prompt


def test_prompt_says_not_to_pick_for_the_user() -> None:
    assert "不要替用户选" in STAGE.system_prompt()
