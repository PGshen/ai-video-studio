"""会话自动命名（`agent/titler.py`）：模型输出的规整，和运行时分派。"""

from __future__ import annotations

import pytest

from studio.agent.titler import TITLE_MAX_CHARS, clean_title, make_title_generator
from studio.db.repo.profiles import ModelProfileValue


def _profile(runtime: str) -> ModelProfileValue:
    return ModelProfileValue(
        id="p",
        name="p",
        provider="x",
        model="m",
        runtime=runtime,
        base_url=None,
        api_key_env=None,
        supports_vision=False,
        price_input=None,
        price_output=None,
        max_cost_per_turn=None,
        max_steps_per_turn=None,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("算法选题头脑风暴", "算法选题头脑风暴"),
        ("「峰终定律选题」", "峰终定律选题"),
        ('标题："记忆与时间"。', "记忆与时间"),
        ("\n  风格库配色调整  \n解释：略", "风格库配色调整"),
        ("一二三四五六七八九十十一十二", "一二三四五六七八九十"),
        ("", None),
        (None, None),
        ("「」。", None),
    ],
)
def test_clean_title(raw: str | None, expected: str | None) -> None:
    result = clean_title(raw)
    assert result == expected
    assert result is None or len(result) <= TITLE_MAX_CHARS


async def test_unsupported_runtime_returns_none() -> None:
    generate = make_title_generator(data_dir=__import__("pathlib").Path("."), environ={})
    assert await generate(_profile("fake"), "你好") is None


async def test_failure_returns_none_instead_of_raising() -> None:
    # openai 运行时没有 api_key_env：建模型时抛错，命名只返回 None。
    generate = make_title_generator(data_dir=__import__("pathlib").Path("."), environ={})
    assert await generate(_profile("openai"), "你好") is None
