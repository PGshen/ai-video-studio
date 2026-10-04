"""风格目录内容的校验与 frontmatter 解析（纯函数）。"""

from __future__ import annotations

import json

import pytest

from studio.styles.validate import (
    MAX_FILE_CHARS,
    MAX_FILES_PER_DIR,
    StyleFiles,
    parse_frontmatter,
    validate_style_files,
)

ENTRY = """---
name: 暖纸双色
description: 暖色纸张质感的双色风格
category: 概念传记
---

# 暖纸双色

先读 `references/color-scheme.md`，写叙事前再看 `exemplars/exemplar-1.json`。
"""

MINIMAL = "---\nname: n\ndescription: d\n---\n"


def _files() -> StyleFiles:
    return {
        "STYLE.md": ENTRY,
        "references/color-scheme.md": "主色：暖白",
        "exemplars/exemplar-1.json": json.dumps({"scenes": []}),
    }


class TestFrontmatter:
    def test_parses_name_description_and_category(self) -> None:
        assert parse_frontmatter(ENTRY) == {
            "name": "暖纸双色",
            "description": "暖色纸张质感的双色风格",
            "category": "概念传记",
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
    def test_valid_style_has_no_errors(self) -> None:
        assert validate_style_files(_files()) == []

    def test_category_is_optional(self) -> None:
        assert validate_style_files({"STYLE.md": MINIMAL}) == []

    def test_entry_is_required(self) -> None:
        errors = validate_style_files({"references/a.md": "x"})
        assert any("STYLE.md" in e and "缺少" in e for e in errors)

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
        errors = validate_style_files({"STYLE.md": content})
        assert any("STYLE.md" in e and needle in e for e in errors)

    def test_name_is_limited_to_100_characters(self) -> None:
        content = f"---\nname: {'x' * 101}\ndescription: d\n---\n"
        assert any("名称过长" in e for e in validate_style_files({"STYLE.md": content}))

    @pytest.mark.parametrize(
        "bad_name",
        ["../evil.md", "a/b.md", ".hidden.md", "a b.md", "x" * 81 + ".md", "a\\b.md"],
    )
    def test_file_names_must_be_plain(self, bad_name: str) -> None:
        errors = validate_style_files({"STYLE.md": MINIMAL, f"references/{bad_name}": "a"})
        assert any("文件名" in e for e in errors)

    @pytest.mark.parametrize(
        "path", ["notes.md", "other/a.md", "../x.md", "/abs.md", ".git/config", "STYLE.md/x"]
    )
    def test_only_the_entry_and_the_two_directories_are_allowed(self, path: str) -> None:
        errors = validate_style_files({"STYLE.md": MINIMAL, path: "x"})
        assert any("不允许的路径" in e and path in e for e in errors)

    def test_a_directory_name_without_a_file_is_not_a_file(self) -> None:
        errors = validate_style_files({"STYLE.md": MINIMAL, "references": "x"})
        assert any("不允许的路径" in e for e in errors)

    def test_same_name_in_different_directories_is_fine(self) -> None:
        files = {"STYLE.md": MINIMAL, "references/a.md": "1", "exemplars/a.md": "2"}
        assert validate_style_files(files) == []

    def test_extensions(self) -> None:
        files = {"STYLE.md": MINIMAL, "references/a.json": "{}", "exemplars/b.py": "x"}
        errors = validate_style_files(files)
        assert any("a.json" in e for e in errors)
        assert any("b.py" in e for e in errors)

    def test_json_exemplar_must_parse(self) -> None:
        errors = validate_style_files({"STYLE.md": MINIMAL, "exemplars/e.json": "{oops"})
        assert any("e.json" in e and "JSON" in e for e in errors)

    def test_entry_references_must_exist(self) -> None:
        files = _files()
        del files["references/color-scheme.md"]
        assert validate_style_files(files) == [
            "STYLE.md 引用了不存在的文件：references/color-scheme.md"
        ]

    def test_directory_mentions_without_a_file_name_are_not_references(self) -> None:
        content = f"{MINIMAL}详见 references/ 目录和 exemplars/*.json。"
        assert validate_style_files({"STYLE.md": content}) == []

    def test_sentence_final_period_is_not_part_of_a_referenced_file_name(self) -> None:
        content = (
            f"{MINIMAL}先读 references/color-scheme.md. 再看 exemplars/exemplar-1.json，"
            "最后是 references/color-scheme.md-。\n"
        )
        files = {
            "STYLE.md": content,
            "references/color-scheme.md": "a",
            "exemplars/exemplar-1.json": "{}",
        }
        assert validate_style_files(files) == []

    def test_a_missing_file_is_reported_without_the_trailing_period(self) -> None:
        files = {"STYLE.md": f"{MINIMAL}先读 references/gone.md.\n"}
        assert validate_style_files(files) == ["STYLE.md 引用了不存在的文件：references/gone.md"]

    def test_size_limits(self) -> None:
        files = {"STYLE.md": MINIMAL, "references/a.md": "x" * (MAX_FILE_CHARS + 1)}
        assert any("过长" in e for e in validate_style_files(files))
        entry = MINIMAL + "x" * MAX_FILE_CHARS
        assert any("STYLE.md 过长" in e for e in validate_style_files({"STYLE.md": entry}))

    def test_file_count_limit_per_directory(self) -> None:
        files = {"STYLE.md": MINIMAL}
        files.update({f"references/f{i}.md": "x" for i in range(MAX_FILES_PER_DIR + 1)})
        assert any("最多" in e for e in validate_style_files(files))
