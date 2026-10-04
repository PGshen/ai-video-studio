"""旧 `style_presets` 表 → 磁盘目录的一次性迁移（ADR 0019；计划 style-library T4）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from studio.db.engine import _alembic_config, migrate
from studio.db.legacy_style_table import StyleTableExportError, export_style_table
from studio.styles import store
from studio.styles.layout import style_dir
from studio.styles.validate import parse_frontmatter

ENTRY = """---
name: 暖纸双色
description: 暖色纸张质感的双色风格
---

先读 `references/color.md`，再看 `exemplars/e1.json`。
"""


def _upgrade(engine: Engine, revision: str) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def _insert(engine: Engine, **overrides: Any) -> str:
    row: dict[str, Any] = {
        "id": "s1",
        "name": "暖纸双色",
        "category": "概念传记",
        "content": ENTRY,
        "description": "暖色纸张质感的双色风格",
        "reference_files": [{"name": "color.md", "text": "主色：暖白"}],
        "exemplars": [{"name": "e1.json", "text": "{}"}],
    }
    row.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO style_presets (id, name, category, content, description, "
                "reference_files, exemplars, created_at) VALUES (:id, :name, :category, "
                ":content, :description, :reference_files, :exemplars, '2026-10-01')"
            ),
            {
                **row,
                "reference_files": json.dumps(row["reference_files"]),
                "exemplars": json.dumps(row["exemplars"]),
            },
        )
    return row["id"]


@pytest.fixture
def old_engine(engine: Engine) -> Engine:
    """迁移到 0006：旧表还在，0007 还没跑。"""
    _upgrade(engine, "0006")
    return engine


def _export(engine: Engine, data_dir: Path) -> Any:
    with engine.begin() as connection:
        return export_style_table(connection, data_dir)


class TestExport:
    def test_a_valid_row_becomes_a_directory_with_the_old_id(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(old_engine)

        report = _export(old_engine, tmp_path)

        assert report.exported == ["s1"]
        detail = store.get_style(tmp_path, "s1")
        assert detail.name == "暖纸双色"
        assert detail.category == "概念传记"
        assert detail.description == "暖色纸张质感的双色风格"
        assert detail.files["references/color.md"] == "主色：暖白"
        assert detail.files["exemplars/e1.json"] == "{}"
        assert detail.files["STYLE.md"].endswith("再看 `exemplars/e1.json`。\n")
        meta = parse_frontmatter(detail.files["STYLE.md"])
        assert meta is not None and meta["category"] == "概念传记"

    def test_row_without_frontmatter_gets_one_from_the_columns(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(
            old_engine,
            content="# 老风格\n\n先读 `references/color.md`。\n",
            reference_files=[{"name": "color.md", "text": "x"}],
            exemplars=[],
        )

        report = _export(old_engine, tmp_path)

        assert report.synthesized_frontmatter == ["暖纸双色"]
        content = store.get_style(tmp_path, "s1").files["STYLE.md"]
        assert parse_frontmatter(content) == {
            "name": "暖纸双色",
            "description": "暖色纸张质感的双色风格",
            "category": "概念传记",
        }
        assert content.endswith("# 老风格\n\n先读 `references/color.md`。\n")

    def test_row_without_description_anywhere_gets_a_fallback(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(
            old_engine, content="# 没有简介\n", description=None, reference_files=[], exemplars=[]
        )

        _export(old_engine, tmp_path)

        detail = store.get_style(tmp_path, "s1")
        assert detail.description

    def test_the_name_and_description_columns_win_over_the_frontmatter(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(old_engine, name="界面上的名字", description="列里的简介")

        report = _export(old_engine, tmp_path)

        assert report.synthesized_frontmatter == ["界面上的名字"]
        detail = store.get_style(tmp_path, "s1")
        assert (detail.name, detail.description) == ("界面上的名字", "列里的简介")

    def test_blank_category_becomes_uncategorized(self, old_engine: Engine, tmp_path: Path) -> None:
        _insert(old_engine, category="  ")

        _export(old_engine, tmp_path)

        assert store.get_style(tmp_path, "s1").category == "未分类"

    def test_directories_that_already_exist_are_skipped_and_left_alone(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(old_engine)
        _export(old_engine, tmp_path)
        (style_dir(tmp_path, "s1") / "references" / "color.md").write_text("用户改过")

        report = _export(old_engine, tmp_path)

        assert report.exported == [] and report.skipped_existing == ["s1"]
        assert (style_dir(tmp_path, "s1") / "references" / "color.md").read_text() == "用户改过"

    def test_invalid_rows_are_reported_and_the_rest_is_still_exported(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(old_engine, id="good")
        _insert(
            old_engine,
            id="bad",
            name="坏风格",
            reference_files=[{"name": "../evil.md", "text": "x"}],
        )

        with pytest.raises(StyleTableExportError) as exc:
            _export(old_engine, tmp_path)

        assert exc.value.report.exported == ["good"]
        assert any("坏风格" in p and "文件名" in p for p in exc.value.report.problems)
        assert store.get_style(tmp_path, "good").name == "暖纸双色"
        assert not style_dir(tmp_path, "bad").exists()

    def test_duplicate_names_are_reported_not_dropped_silently(
        self, old_engine: Engine, tmp_path: Path
    ) -> None:
        _insert(old_engine, id="s1")
        _insert(old_engine, id="s2")

        with pytest.raises(StyleTableExportError) as exc:
            _export(old_engine, tmp_path)

        assert len(exc.value.report.exported) == 1
        assert any("重名" in p or "同名" in p for p in exc.value.report.problems)

    def test_empty_table_exports_nothing(self, old_engine: Engine, tmp_path: Path) -> None:
        report = _export(old_engine, tmp_path)

        assert report.exported == [] and report.problems == []


class TestMigration0007:
    def test_exports_next_to_the_database_and_drops_the_table(
        self, old_engine: Engine, db_path: Path
    ) -> None:
        _insert(old_engine)

        migrate(old_engine)

        assert "style_presets" not in inspect(old_engine).get_table_names()
        assert store.get_style(db_path.parent, "s1").name == "暖纸双色"

    def test_a_failing_export_keeps_the_table_and_a_retry_succeeds(
        self, old_engine: Engine, db_path: Path
    ) -> None:
        _insert(old_engine, id="good")
        _insert(
            old_engine,
            id="bad",
            name="坏风格",
            content="没有 frontmatter",
            reference_files=[{"name": "x y.md", "text": "x"}],
        )

        with pytest.raises(StyleTableExportError):
            migrate(old_engine)
        assert "style_presets" in inspect(old_engine).get_table_names()

        with old_engine.begin() as connection:
            connection.execute(text("DELETE FROM style_presets WHERE id = 'bad'"))
        migrate(old_engine)

        assert "style_presets" not in inspect(old_engine).get_table_names()
        assert [s.id for s in store.list_styles(db_path.parent)] == ["good"]

    def test_a_fresh_database_has_no_style_table_and_no_styles_directory(
        self, migrated_engine: Engine, db_path: Path
    ) -> None:
        assert "style_presets" not in inspect(migrated_engine).get_table_names()
        assert not (db_path.parent / "styles").exists()

    def test_rows_written_before_migration_0004_are_exported_too(
        self, engine: Engine, db_path: Path
    ) -> None:
        _upgrade(engine, "0003")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO style_presets (id, name, category, content, exemplars, "
                    "created_at) VALUES ('old', '最早的风格', '旧', '# 只有正文', '[]', "
                    "'2026-09-01')"
                )
            )

        migrate(engine)

        detail = store.get_style(db_path.parent, "old")
        assert detail.name == "最早的风格" and detail.category == "旧"
        assert detail.description
        assert detail.files["STYLE.md"].endswith("# 只有正文")
