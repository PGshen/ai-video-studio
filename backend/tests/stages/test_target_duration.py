"""`stages.common.target_duration`：从 `brief.md` 读出目标时长（秒）。"""

from __future__ import annotations

import pytest

from studio.stages.common.target_duration import parse_target_seconds


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30 秒", 30.0),
        ("30秒", 30.0),
        ("约 45 秒左右", 45.0),
        ("1.5 分钟", 90.0),
        ("2 分钟", 120.0),
        ("90s", 90.0),
        ("目标 60 sec", 60.0),
        ("0.5 分", 30.0),
    ],
)
def test_parses_seconds_and_minutes(text: str, expected: float) -> None:
    assert parse_target_seconds(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "很短", "30", "一分钟", "-5 秒", "0 秒"])
def test_unparseable_or_non_positive_is_none(text: str) -> None:
    assert parse_target_seconds(text) is None


def test_target_is_read_from_the_named_section_only() -> None:
    from studio.stages.common.target_duration import target_seconds_from_brief

    text = "## 主题\n\n约 99 秒的故事\n\n## 2. 目标时长\n\n45 秒\n\n## 风险点\n\n10 秒\n"
    assert target_seconds_from_brief(text) == pytest.approx(45.0)
    assert target_seconds_from_brief("## 主题\n\n30 秒\n") is None
    assert target_seconds_from_brief("## 目标时长\n\n很短\n") is None
