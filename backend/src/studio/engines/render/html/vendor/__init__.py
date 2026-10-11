"""Third-party libraries bundled with the HTML engine (ADR 0028).

The files are produced once by `scripts/vendor_three.sh` and checked in; nothing is fetched
at runtime.
`three.iife.js` is the three.js core built as a classic script that defines the global `THREE`.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

VENDOR_DIR = Path(__file__).parent
THREE_IIFE = VENDOR_DIR / "three.iife.js"
THREE_LICENSE = VENDOR_DIR / "three.LICENSE"
THREE_SCRIPT_NAME = "vendor/three.js"


@cache
def three_version() -> str:
    return (VENDOR_DIR / "THREE_VERSION").read_text(encoding="utf-8").strip()


@cache
def three_script() -> str:
    return THREE_IIFE.read_text(encoding="utf-8")
