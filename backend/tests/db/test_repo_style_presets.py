"""`style_presets` 仓储与校验（计划 M5 T2）：skill 形态目录——入口 + 引用文件 + 金样本。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from studio.db.engine import _alembic_config, migrate
from studio.db.repo.style_presets import (
    DuplicateStylePresetError,
    StyleFile,
    StylePresetNotFoundError,
    StylePresetValidationError,
    create_style_preset,
    delete_style_preset,
    duplicate_style_preset,
    get_style_preset,
    list_style_preset_summaries,
    list_style_presets,
    parse_frontmatter,
    update_style_preset,
    validate_style_preset,
)

ENTRY = """---
name: 暖纸双色
description: 暖色纸张质感的双色风格
---

# 暖纸双色

先读 `references/color-scheme.md`，写叙事前再看 `exemplars/exemplar-1.json`。
"""


def _create(engine: Engine, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "name": "暖纸双色",
        "category": "概念传记",
        "description": None,
        "content": ENTRY,
        "references": [StyleFile("color-scheme.md", "主色：暖白")],
        "exemplars": [StyleFile("exemplar-1.json", json.dumps({"scenes": []}))],
    }
    fields.update(overrides)
    return create_style_preset(engine, **fields)


class TestFrontmatter:
    def test_parses_name_and_description(self) -> None:
        assert parse_frontmatter(ENTRY) == {
            "name": "暖纸双色",
            "description": "暖色纸张质感的双色风格",
        }

    @pytest.mark.parametrize("value", ['"带: 冒号"', "'带: 冒号'"])
    def test_strips_matching_quotes(self, value: str) -> None:
        assert parse_frontmatter(f"---\nname: {value}\n---\n") == {"name": "带: 冒号"}

    def test_unescapes_double_quoted_values(self) -> None:
        content = '---\nname: "带\\"引号\\"和\\\\反斜杠"\n---\n'
        assert parse_frontmatter(content) == {"name": '带"引号"和\\反斜杠'}

    @pytest.mark.parametrize("content", ["# 没有 frontmatter\n", "---\nname: x\n", ""])
    def test_returns_none_without_a_closed_block(self, content: str) -> None:
        assert parse_frontmatter(content) is None


class TestValidate:
    def test_valid_preset_has_no_errors(self) -> None:
        assert (
            validate_style_preset(
                name="x",
                content=ENTRY,
                references=[StyleFile("color-scheme.md", "a")],
                exemplars=[StyleFile("exemplar-1.json", "{}")],
            )
            == []
        )

    @pytest.mark.parametrize(
        ("content", "needle"),
        [
            ("# 没有 frontmatter", "frontmatter"),
            ("---\ndescription: d\n---\n", "name"),
            ("---\nname: n\n---\n", "description"),
            ("---\nname:  \ndescription: d\n---\n", "name"),
        ],
    )
    def test_entry_needs_name_and_description(self, content: str, needle: str) -> None:
        errors = validate_style_preset(name="x", content=content, references=[], exemplars=[])
        assert any("STYLE.md" in e and needle in e for e in errors)

    @pytest.mark.parametrize(
        "bad_name",
        ["../evil.md", "a/b.md", "/abs.md", "..", ".hidden.md", "", "a b.md", "x" * 81 + ".md"],
    )
    def test_file_names_must_be_plain(self, bad_name: str) -> None:
        errors = validate_style_preset(
            name="x", content=ENTRY, references=[StyleFile(bad_name, "a")], exemplars=[]
        )
        assert any("文件名" in e for e in errors)

    def test_duplicate_names_in_one_directory(self) -> None:
        errors = validate_style_preset(
            name="x",
            content="---\nname: n\ndescription: d\n---\n",
            references=[StyleFile("a.md", "1"), StyleFile("a.md", "2")],
            exemplars=[],
        )
        assert any("重复" in e and "a.md" in e for e in errors)

    def test_same_name_in_different_directories_is_fine(self) -> None:
        errors = validate_style_preset(
            name="x",
            content="---\nname: n\ndescription: d\n---\n",
            references=[StyleFile("a.md", "1")],
            exemplars=[StyleFile("a.md", "2")],
        )
        assert errors == []

    def test_extensions(self) -> None:
        errors = validate_style_preset(
            name="x",
            content="---\nname: n\ndescription: d\n---\n",
            references=[StyleFile("a.json", "{}")],
            exemplars=[StyleFile("b.py", "x")],
        )
        assert any("a.json" in e for e in errors)
        assert any("b.py" in e for e in errors)

    def test_json_exemplar_must_parse(self) -> None:
        errors = validate_style_preset(
            name="x",
            content="---\nname: n\ndescription: d\n---\n",
            references=[],
            exemplars=[StyleFile("e.json", "{oops")],
        )
        assert any("e.json" in e and "JSON" in e for e in errors)

    def test_entry_references_must_exist(self) -> None:
        errors = validate_style_preset(
            name="x", content=ENTRY, references=[], exemplars=[StyleFile("exemplar-1.json", "{}")]
        )
        assert errors == ["STYLE.md 引用了不存在的文件：references/color-scheme.md"]

    def test_directory_mentions_without_a_file_name_are_not_references(self) -> None:
        content = "---\nname: n\ndescription: d\n---\n详见 references/ 目录和 exemplars/*.json。"
        assert validate_style_preset(name="x", content=content, references=[], exemplars=[]) == []

    def test_size_and_count_limits(self) -> None:
        big = StyleFile("a.md", "x" * 200_001)
        many = [StyleFile(f"f{i}.md", "x") for i in range(31)]
        content = "---\nname: n\ndescription: d\n---\n"
        assert any(
            "过长" in e
            for e in validate_style_preset(
                name="x", content=content, references=[big], exemplars=[]
            )
        )
        assert any(
            "最多" in e
            for e in validate_style_preset(name="x", content=content, references=many, exemplars=[])
        )

    def test_name_is_required(self) -> None:
        assert validate_style_preset(name="  ", content=ENTRY, references=[], exemplars=[])


class TestCrud:
    def test_create_and_get_round_trip(self, migrated_engine: Engine) -> None:
        created = _create(migrated_engine)

        got = get_style_preset(migrated_engine, created.id)
        assert got is not None
        assert got.name == "暖纸双色"
        assert got.category == "概念传记"
        assert got.content == ENTRY
        assert got.references == [StyleFile("color-scheme.md", "主色：暖白")]
        assert got.exemplars == [StyleFile("exemplar-1.json", '{"scenes": []}')]

    def test_description_defaults_to_the_frontmatter_one(self, migrated_engine: Engine) -> None:
        assert _create(migrated_engine).description == "暖色纸张质感的双色风格"
        other = _create(migrated_engine, name="另一套", description="自己写的")
        assert other.description == "自己写的"

    def test_invalid_preset_is_rejected_and_not_stored(self, migrated_engine: Engine) -> None:
        with pytest.raises(StylePresetValidationError) as info:
            _create(migrated_engine, references=[])
        assert "references/color-scheme.md" in str(info.value)
        assert list_style_presets(migrated_engine) == []

    def test_names_are_unique_after_trimming(self, migrated_engine: Engine) -> None:
        _create(migrated_engine)
        with pytest.raises(DuplicateStylePresetError):
            _create(migrated_engine, name="  暖纸双色 ")

    def test_list_is_ordered_by_category_then_name(self, migrated_engine: Engine) -> None:
        _create(migrated_engine, name="b", category="B")
        _create(migrated_engine, name="c", category="A")
        _create(migrated_engine, name="a", category="B")

        names = [p.name for p in list_style_presets(migrated_engine)]
        assert names == ["c", "a", "b"]

    def test_update_changes_only_given_fields_and_replaces_lists(
        self, migrated_engine: Engine
    ) -> None:
        created = _create(migrated_engine)

        updated = update_style_preset(
            migrated_engine,
            created.id,
            category="新分类",
            references=[StyleFile("color-scheme.md", "新配色"), StyleFile("extra.md", "x")],
        )

        assert updated.category == "新分类"
        assert updated.name == "暖纸双色"
        assert updated.content == ENTRY
        assert [f.name for f in updated.references] == ["color-scheme.md", "extra.md"]
        assert updated.exemplars == created.exemplars

    def test_update_validates_the_merged_result(self, migrated_engine: Engine) -> None:
        created = _create(migrated_engine)

        with pytest.raises(StylePresetValidationError):
            update_style_preset(migrated_engine, created.id, references=[])

        got = get_style_preset(migrated_engine, created.id)
        assert got is not None and len(got.references) == 1

    def test_rename_to_an_existing_name_is_rejected(self, migrated_engine: Engine) -> None:
        _create(migrated_engine)
        other = _create(migrated_engine, name="另一套")
        with pytest.raises(DuplicateStylePresetError):
            update_style_preset(migrated_engine, other.id, name="暖纸双色")
        # 改成自己的名字不算重复
        assert update_style_preset(migrated_engine, other.id, name="另一套").name == "另一套"

    def test_unknown_id(self, migrated_engine: Engine) -> None:
        assert get_style_preset(migrated_engine, "nope") is None
        with pytest.raises(StylePresetNotFoundError):
            update_style_preset(migrated_engine, "nope", category="x")
        with pytest.raises(StylePresetNotFoundError):
            delete_style_preset(migrated_engine, "nope")
        with pytest.raises(StylePresetNotFoundError):
            duplicate_style_preset(migrated_engine, "nope")

    def test_delete(self, migrated_engine: Engine) -> None:
        created = _create(migrated_engine)
        delete_style_preset(migrated_engine, created.id)
        assert get_style_preset(migrated_engine, created.id) is None

    def test_duplicate_is_independent_and_gets_a_fresh_name(self, migrated_engine: Engine) -> None:
        created = _create(migrated_engine)

        first = duplicate_style_preset(migrated_engine, created.id)
        second = duplicate_style_preset(migrated_engine, created.id)

        assert first.name == "暖纸双色（副本）"
        assert second.name == "暖纸双色（副本 2）"
        assert first.id != created.id
        update_style_preset(migrated_engine, first.id, category="改了")
        original = get_style_preset(migrated_engine, created.id)
        assert original is not None and original.category == "概念传记"
        assert first.references == created.references


class TestMigration0004:
    def test_columns_exist(self, migrated_engine: Engine) -> None:
        columns = {c["name"] for c in inspect(migrated_engine).get_columns("style_presets")}
        assert {"description", "reference_files"} <= columns

    def test_rows_written_before_the_migration_stay_readable(self, engine: Engine) -> None:
        config = _alembic_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0003")
            connection.execute(
                text(
                    "INSERT INTO style_presets (id, name, category, content, exemplars, created_at)"
                    " VALUES ('old', '旧预设', '旧', '# 旧内容', NULL, '2026-09-01 00:00:00')"
                )
            )

        migrate(engine)

        got = get_style_preset(engine, "old")
        assert got is not None
        assert got.name == "旧预设"
        assert got.content == "# 旧内容"
        assert got.references == []
        assert got.exemplars == []
        assert got.description is None


class TestReviewFixes:
    """M5 评审发现的问题：句末句号、清空简介、列表摘要不读正文。"""

    def test_sentence_final_period_is_not_part_of_a_referenced_file_name(self) -> None:
        content = (
            "---\nname: n\ndescription: d\n---\n"
            "先读 references/color-scheme.md. 再看 exemplars/exemplar-1.json，"
            "最后是 references/color-scheme.md-。\n"
        )

        errors = validate_style_preset(
            name="x",
            content=content,
            references=[StyleFile("color-scheme.md", "a")],
            exemplars=[StyleFile("exemplar-1.json", "{}")],
        )

        assert errors == []

    def test_a_missing_file_is_still_reported_without_the_trailing_period(self) -> None:
        content = "---\nname: n\ndescription: d\n---\n先读 references/gone.md.\n"

        errors = validate_style_preset(name="x", content=content, references=[], exemplars=[])

        assert errors == ["STYLE.md 引用了不存在的文件：references/gone.md"]

    def test_update_can_clear_the_description_but_leaves_it_when_not_given(
        self, migrated_engine: Engine
    ) -> None:
        created = _create(migrated_engine, description="自己写的简介")

        untouched = update_style_preset(migrated_engine, created.id, category="新分类")
        assert untouched.description == "自己写的简介"

        cleared = update_style_preset(migrated_engine, created.id, description=None)
        assert cleared.description is None
        got = get_style_preset(migrated_engine, created.id)
        assert got is not None and got.description is None

    def test_summaries_carry_counts_and_are_sorted_like_the_full_list(
        self, migrated_engine: Engine
    ) -> None:
        _create(migrated_engine, name="b", category="B")
        _create(
            migrated_engine,
            name="a",
            category="A",
            content="---\nname: a\ndescription: d\n---\n",
            references=[StyleFile("color-scheme.md", "x"), StyleFile("extra.md", "y")],
            exemplars=[],
        )

        summaries = list_style_preset_summaries(migrated_engine)

        assert [(s.name, s.category) for s in summaries] == [("a", "A"), ("b", "B")]
        assert (summaries[0].reference_count, summaries[0].exemplar_count) == (2, 0)
        assert (summaries[1].reference_count, summaries[1].exemplar_count) == (1, 1)

    def test_summaries_of_rows_written_before_migration_0004_count_zero(
        self, engine: Engine
    ) -> None:
        config = _alembic_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0003")
            connection.execute(
                text(
                    "INSERT INTO style_presets (id, name, category, content, exemplars, created_at)"
                    " VALUES ('old', '旧预设', '旧', '# 旧内容', NULL, '2026-09-01 00:00:00')"
                )
            )
        migrate(engine)

        [summary] = list_style_preset_summaries(engine)

        assert (summary.reference_count, summary.exemplar_count) == (0, 0)
