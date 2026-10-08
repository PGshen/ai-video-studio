"""Tests for scripts/check_docs.py::check_tech_debt_ids.

The script lives outside the backend package (stdlib only, run by `make check-docs`),
so it is loaded by path. These tests are collected by the backend pytest run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_docs", REPO_ROOT / "scripts" / "check_docs.py"
)
assert _spec is not None and _spec.loader is not None
check_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_docs)

PATH = REPO_ROOT / "docs" / "quality" / "tech-debt.md"


def _doc(open_rows: list[str], done_rows: list[str]) -> str:
    return "\n".join(
        [
            "# 技术债",
            "",
            "| # | x |",
            "|---|---|",
            *open_rows,
            "",
            "## 已处理",
            "",
            "| # | y |",
            "|---|---|",
            *done_rows,
            "",
        ]
    )


def test_open_and_processed_collision_is_error() -> None:
    errors = check_docs.check_tech_debt_ids(PATH, _doc(["| TD-5 | a |"], ["| TD-5 | done |"]))
    assert len(errors) == 1
    assert "TD-5" in errors[0]
    assert "未处理表" in errors[0] and "已处理表" in errors[0]


def test_row_without_spaces_is_recognised() -> None:
    errors = check_docs.check_tech_debt_ids(PATH, _doc(["|TD-60|a|", "| TD-60 | b |"], []))
    assert len(errors) == 1
    assert "TD-60" in errors[0]


def test_row_without_spaces_collides_with_processed() -> None:
    errors = check_docs.check_tech_debt_ids(PATH, _doc(["|TD-61|a|"], ["|TD-61| done |"]))
    assert len(errors) == 1 and "TD-61" in errors[0]


def test_partial_processed_rows_do_not_collide() -> None:
    done = [
        "| TD-25（预算部分） | d |",
        "| TD-27（部分） | d |",
        "| TD-39（Claude 侧） | d |",
        "| — | d |",
    ]
    open_rows = ["| TD-25 | a |", "| TD-27 | a |", "| TD-39 | a |"]
    assert check_docs.check_tech_debt_ids(PATH, _doc(open_rows, done)) == []


def test_real_tech_debt_file_passes() -> None:
    text = PATH.read_text(encoding="utf-8")
    assert check_docs.check_tech_debt_ids(PATH, text) == []
