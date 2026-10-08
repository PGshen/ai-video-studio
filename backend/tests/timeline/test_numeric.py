"""Shared grid constants and the finite-number guard used by `build` and `imported` (TD-74)."""

from __future__ import annotations

import math

import pytest

from studio.timeline import build, imported
from studio.timeline.numeric import BEATS_PER_BAR, EPSILON, is_finite_number


@pytest.mark.parametrize("value", [0, 1, -2.5, 1e9, 0.0])
def test_finite_numbers_are_accepted(value: float) -> None:
    assert is_finite_number(value) is True


@pytest.mark.parametrize("value", [True, False, None, "1", math.nan, math.inf, -math.inf, [1]])
def test_bools_non_numbers_and_non_finite_values_are_rejected(value: object) -> None:
    assert is_finite_number(value) is False


def test_the_grid_modules_share_one_definition() -> None:
    assert (BEATS_PER_BAR, EPSILON) == (4, 1e-6)
    assert build.is_finite_number is is_finite_number
    assert imported.is_finite_number is is_finite_number
