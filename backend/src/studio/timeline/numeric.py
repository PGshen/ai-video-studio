"""Grid constants and the finite-number guard shared by `build` and `imported` (TD-74)."""

from __future__ import annotations

import math
from typing import Any, TypeGuard

BEATS_PER_BAR = 4
EPSILON = 1e-6


def is_finite_number(value: Any) -> TypeGuard[float]:
    """A real, finite `int`/`float` (bools and NaN/inf are not numbers here)."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
