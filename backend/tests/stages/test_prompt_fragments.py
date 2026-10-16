"""共享提示词片段（free-mode 设计 §4.4，计划 T4）。

多阶段提示词改为"阶段自己的段落 + 共享片段"拼接；拼接结果必须与重构前逐字相同。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.agent.stage import StageDefinition
from studio.stages.animation_html import STAGE as ANIMATION_HTML
from studio.stages.common.prompts import compose_prompt, fragment
from studio.stages.music import STAGE as MUSIC
from studio.stages.narrative import STAGE as NARRATIVE
from studio.stages.produce import STAGE as PRODUCE


@pytest.mark.parametrize(
    ("stage", "heading", "fragments"),
    [
        (NARRATIVE, "# 叙事阶段", ["narration-schema", "narration-writing"]),
        (ANIMATION_HTML, "# 动画阶段（HTML 画面）", ["scenes-explainer"]),
        (PRODUCE, "# 配乐与动画", ["silent-compose", "silent-song", "silent-scenes"]),
        (MUSIC, "# 配乐阶段", ["music-explainer"]),
    ],
)
def test_staged_prompts_embed_their_shared_fragments(
    stage: StageDefinition, heading: str, fragments: list[str]
) -> None:
    prompt = stage.system_prompt()
    assert prompt is not None
    assert prompt.startswith(heading)
    for name in fragments:
        assert fragment(name).read_text(encoding="utf-8") in prompt, name


@pytest.mark.parametrize(
    ("name", "anchor"),
    [
        ("narration-schema", "### beats 的四个字段"),
        ("narration-writing", "## 写作方式"),
        ("scenes-explainer", "## env 契约"),
        ("music-explainer", "STUDIO_TIMELINE"),
        ("silent-compose", "STUDIO_OUT_EVENTS"),
        ("silent-song", "music/range.json"),
        ("silent-scenes", "animation/shots.json"),
    ],
)
def test_fragments_keep_their_contract(name: str, anchor: str) -> None:
    assert anchor in fragment(name).read_text(encoding="utf-8")


def test_unknown_fragment_is_an_error() -> None:
    with pytest.raises(ValueError, match="no-such-fragment"):
        fragment("no-such-fragment")


def test_compose_prompt_concatenates_in_order(tmp_path: Path) -> None:
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("# A\n\n", encoding="utf-8")
    b.write_text("## B\n", encoding="utf-8")
    assert compose_prompt(a, b) == "# A\n\n## B\n"


def test_narration_schema_names_html_scene_files() -> None:
    text = fragment("narration-schema").read_text(encoding="utf-8")
    assert "animation/scenes/<id>.js" in text
    assert ".py" not in text
