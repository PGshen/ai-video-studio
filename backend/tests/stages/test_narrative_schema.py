"""`stages.narrative.schema` 测试（计划 M3 T3）。"""

from __future__ import annotations

import pytest

from studio.stages.narrative.schema import NarrativeValidationError, validate_and_normalize

_VALID_DOC = {
    "scenes": [
        {
            "id": "s-hook",
            "narration": "如果一个排序算法能在一秒内处理十亿条记录",
            "visual_intent": "用一个不断增长的数字条引出问题",
            "beats": [
                {
                    "cue_text": "如果一个排序算法能在一秒内处理十亿条记录",
                    "visual_action": "数字条从左侧滑入",
                    "emphasis": "强调数字规模",
                    "transition": "reveal",
                }
            ],
        },
        {
            "id": "s-explain",
            "narration": "答案是分而治之",
            "visual_intent": "用分裂再合并的动画展示分治思想",
            "beats": [
                {
                    "cue_text": "答案是",
                    "visual_action": "一个大方块出现",
                    "emphasis": "引出",
                    "transition": "continue",
                },
                {
                    "cue_text": "分而治之",
                    "visual_action": "方块裂成两半",
                    "emphasis": "点出核心概念",
                    "transition": "transform",
                },
            ],
        },
    ]
}


def test_valid_document_passes() -> None:
    narrative = validate_and_normalize(_VALID_DOC)
    assert [scene.id for scene in narrative.scenes] == ["s-hook", "s-explain"]
    assert narrative.scenes[1].beats[1].transition == "transform"


def test_empty_scenes_rejected() -> None:
    with pytest.raises(NarrativeValidationError) as exc_info:
        validate_and_normalize({"scenes": []})
    assert any("scenes" in error for error in exc_info.value.errors)


def test_duplicate_scene_id_rejected() -> None:
    doc = {
        "scenes": [
            {**_VALID_DOC["scenes"][0]},
            {**_VALID_DOC["scenes"][0]},
        ]
    }
    with pytest.raises(NarrativeValidationError) as exc_info:
        validate_and_normalize(doc)
    assert any("s-hook" in error for error in exc_info.value.errors)


def test_cue_text_must_cover_narration_exactly() -> None:
    doc = {
        "scenes": [
            {
                "id": "s-hook",
                "narration": "甲乙丙丁",
                "visual_intent": "x",
                "beats": [
                    {
                        "cue_text": "甲乙",
                        "visual_action": "x",
                        "emphasis": "x",
                        "transition": "continue",
                    }
                ],
            }
        ]
    }
    with pytest.raises(NarrativeValidationError) as exc_info:
        validate_and_normalize(doc)
    assert any("s-hook" in error for error in exc_info.value.errors)


def test_invalid_transition_rejected() -> None:
    doc = {
        "scenes": [
            {
                "id": "s-hook",
                "narration": "甲",
                "visual_intent": "x",
                "beats": [
                    {"cue_text": "甲", "visual_action": "x", "emphasis": "x", "transition": "boom"}
                ],
            }
        ]
    }
    with pytest.raises(NarrativeValidationError) as exc_info:
        validate_and_normalize(doc)
    assert any("s-hook" in error for error in exc_info.value.errors)


def test_empty_beats_rejected() -> None:
    doc = {
        "scenes": [
            {"id": "s-hook", "narration": "甲", "visual_intent": "x", "beats": []},
        ]
    }
    with pytest.raises(NarrativeValidationError) as exc_info:
        validate_and_normalize(doc)
    assert any("s-hook" in error for error in exc_info.value.errors)
