"""旧项目风格导入（计划 M5 T4）：旧 `style_templates` + `prompt_components` 的导出 → 风格预设。

fixture 的结构照真实导出（`scripts/export_legacy_styles.sh`）手写：模板的 `style_config`
把四个类别（`narrative_style`/`color_scheme`/`animation_style`/`exemplar`）映射到组件 id。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from studio.db.legacy_styles import (
    LegacyExportError,
    import_export,
    load_export,
    main,
)
from studio.styles import store
from studio.styles.validate import (
    parse_frontmatter,
    set_frontmatter_fields,
    validate_style_files,
)


@dataclass(frozen=True)
class _File:
    name: str
    text: str


@dataclass(frozen=True)
class _Preset:
    """风格目录的旧「预设」视图，方便沿用原来的断言。"""

    id: str
    name: str
    category: str
    description: str | None
    content: str
    references: list[_File]
    exemplars: list[_File]


def _preset(data_dir: Path, style_id: str) -> _Preset:
    detail = store.get_style(data_dir, style_id)

    def _in(prefix: str) -> list[_File]:
        return [_File(p[len(prefix) :], t) for p, t in detail.files.items() if p.startswith(prefix)]

    return _Preset(
        id=detail.id,
        name=detail.name,
        category=detail.category,
        description=detail.description,
        content=detail.files["STYLE.md"],
        references=_in("references/"),
        exemplars=_in("exemplars/"),
    )


def list_style_presets(data_dir: Path) -> list[_Preset]:
    return [_preset(data_dir, s.id) for s in store.list_styles(data_dir)]


def get_style_preset(data_dir: Path, style_id: str) -> _Preset:
    return _preset(data_dir, style_id)


def update_category(data_dir: Path, style_id: str, category: str) -> None:
    files = dict(store.get_style(data_dir, style_id).files)
    files["STYLE.md"] = set_frontmatter_fields(files["STYLE.md"], {"category": category})
    store.import_style(data_dir, files, style_id=style_id, overwrite=True)


NEW_FORMAT_EXEMPLAR = json.dumps(
    {"scenes": [{"id": "s-hook", "narration": "x"}]}, ensure_ascii=False
)
LEGACY_EXEMPLAR = json.dumps(
    {"scenes": [{"scene_index": 0, "narration": "x", "description": "d", "beats": []}]},
    ensure_ascii=False,
)


def _component(cid: str, category: str, text: str, name: str | None = None) -> dict[str, Any]:
    return {
        "id": cid,
        "category": category,
        "name": name or f"{category}-{cid}",
        "description": None,
        "prompt_text": text,
        "is_builtin": True,
    }


def _template(
    name: str, config: dict[str, str], description: str | None = "一套风格"
) -> dict[str, Any]:
    return {"id": f"t-{name}", "name": name, "description": description, "style_config": config}


def _export(templates: list[dict[str, Any]], components: list[dict[str, Any]]) -> dict[str, Any]:
    return {"templates": templates, "components": components}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _full_export() -> dict[str, Any]:
    return _export(
        [
            _template(
                "概念传记·纸上溯源",
                {
                    "narrative_style": "n1",
                    "color_scheme": "c1",
                    "animation_style": "a1",
                    "exemplar": "e1",
                },
            )
        ],
        [
            _component("n1", "narrative_style", "【叙事蓝图】\n四问骨架"),
            _component("c1", "color_scheme", "主色：暖白"),
            _component("a1", "animation_style", "原地生长"),
            _component("e1", "exemplar", LEGACY_EXEMPLAR),
        ],
    )


class TestConversion:
    def test_full_template_becomes_a_skill_style_directory(self, data_dir: Path) -> None:
        report = import_export(data_dir, _full_export())

        assert report.created == ["概念传记·纸上溯源"]
        preset = list_style_presets(data_dir)[0]
        assert preset.name == "概念传记·纸上溯源"
        assert preset.category == "旧项目导入"
        assert preset.description == "一套风格"
        assert {f.name for f in preset.references} == {
            "narrative-blueprint.md",
            "color-scheme.md",
            "animation-style.md",
        }
        assert [f.name for f in preset.exemplars] == ["exemplar-1.json"]

    def test_component_text_is_copied_verbatim(self, data_dir: Path) -> None:
        import_export(data_dir, _full_export())

        preset = list_style_presets(data_dir)[0]
        by_name = {f.name: f.text for f in preset.references}
        assert by_name["narrative-blueprint.md"] == "【叙事蓝图】\n四问骨架"
        assert by_name["color-scheme.md"] == "主色：暖白"
        assert by_name["animation-style.md"] == "原地生长"
        assert preset.exemplars[0].text == LEGACY_EXEMPLAR

    def test_entry_is_valid_and_indexes_every_file_with_when_to_read(self, data_dir: Path) -> None:
        import_export(data_dir, _full_export())

        preset = list_style_presets(data_dir)[0]
        assert parse_frontmatter(preset.content) == {
            "name": "概念传记·纸上溯源",
            "description": "一套风格",
            "category": "旧项目导入",
        }
        files = {"STYLE.md": preset.content}
        files.update({f"references/{f.name}": f.text for f in preset.references})
        files.update({f"exemplars/{f.name}": f.text for f in preset.exemplars})
        assert validate_style_files(files) == []
        for path in (
            "references/narrative-blueprint.md",
            "references/color-scheme.md",
            "references/animation-style.md",
            "exemplars/exemplar-1.json",
        ):
            assert path in preset.content
        assert "叙事" in preset.content and "动画" in preset.content and "选题" in preset.content

    def test_color_scheme_is_read_in_both_narrative_and_animation_stages(
        self, data_dir: Path
    ) -> None:
        import_export(data_dir, _full_export())

        content = list_style_presets(data_dir)[0].content
        row = next(line for line in content.splitlines() if "references/color-scheme.md" in line)
        assert "叙事阶段" in row and "动画阶段" in row

    def test_legacy_format_exemplar_is_flagged_in_entry_and_report(self, data_dir: Path) -> None:
        report = import_export(data_dir, _full_export())

        preset = list_style_presets(data_dir)[0]
        assert "旧格式" in preset.content
        assert report.legacy_format_exemplars == ["概念传记·纸上溯源"]

    def test_blueprint_using_old_field_names_is_flagged_and_defers_to_the_stage_prompt(
        self, data_dir: Path
    ) -> None:
        export = _full_export()
        export["components"][0]["prompt_text"] = (
            "每镜输出 scene_index 与 estimated_duration_seconds"
        )
        export["components"][3]["prompt_text"] = NEW_FORMAT_EXEMPLAR

        report = import_export(data_dir, export)

        assert report.legacy_field_blueprints == ["概念传记·纸上溯源"]
        assert report.legacy_format_exemplars == []
        content = list_style_presets(data_dir)[0].content
        assert "旧格式提示" in content
        assert "references/narrative-blueprint.md" in content.split("旧格式提示")[1]
        assert "系统提示词为准" in content

    def test_notice_lists_every_affected_file(self, data_dir: Path) -> None:
        export = _full_export()
        export["components"][0]["prompt_text"] = "beat_index"

        import_export(data_dir, export)

        notice = list_style_presets(data_dir)[0].content.split("旧格式提示")[1]
        assert "references/narrative-blueprint.md" in notice
        assert "exemplars/exemplar-1.json" in notice

    def test_new_format_exemplar_is_not_flagged(self, data_dir: Path) -> None:
        export = _full_export()
        export["components"][3]["prompt_text"] = NEW_FORMAT_EXEMPLAR

        report = import_export(data_dir, export)

        assert report.legacy_format_exemplars == []
        assert "旧格式" not in list_style_presets(data_dir)[0].content

    def test_non_json_exemplar_becomes_markdown(self, data_dir: Path) -> None:
        export = _full_export()
        export["components"][3]["prompt_text"] = "这是一段散文式的范例"

        import_export(data_dir, export)

        assert [f.name for f in list_style_presets(data_dir)[0].exemplars] == ["exemplar-1.md"]

    @pytest.mark.parametrize("name", ["带: 冒号的名字", '带"引号"的名字', "带 # 井号"])
    def test_awkward_names_survive_the_frontmatter(self, data_dir: Path, name: str) -> None:
        export = _full_export()
        export["templates"][0]["name"] = name

        report = import_export(data_dir, export)

        assert report.problems == []
        preset = list_style_presets(data_dir)[0]
        front = parse_frontmatter(preset.content)
        assert front is not None and front["name"].strip() != ""

    def test_multiline_description_is_flattened_for_the_frontmatter(self, data_dir: Path) -> None:
        export = _full_export()
        export["templates"][0]["description"] = "第一行\n第二行"

        import_export(data_dir, export)

        front = parse_frontmatter(list_style_presets(data_dir)[0].content)
        assert front is not None and "第一行" in front["description"]
        assert "\n" not in front["description"]

    def test_template_without_description_gets_a_fallback(self, data_dir: Path) -> None:
        export = _full_export()
        export["templates"][0]["description"] = None

        report = import_export(data_dir, export)

        assert report.created == ["概念传记·纸上溯源"]
        assert list_style_presets(data_dir)[0].description


class TestMissingPieces:
    def _one(self, config: dict[str, str], components: list[dict[str, Any]]) -> dict[str, Any]:
        return _export([_template("T", config)], components)

    def test_missing_category_is_imported_with_a_warning_and_noted_in_entry(
        self, data_dir: Path
    ) -> None:
        export = self._one(
            {"color_scheme": "c1", "animation_style": "a1"},
            [_component("c1", "color_scheme", "配色"), _component("a1", "animation_style", "动画")],
        )

        report = import_export(data_dir, export)

        assert report.created == ["T"]
        assert any("T" in p and "narrative_style" in p for p in report.problems)
        assert any("T" in p and "exemplar" in p for p in report.problems)
        preset = list_style_presets(data_dir)[0]
        assert {f.name for f in preset.references} == {"color-scheme.md", "animation-style.md"}
        assert preset.exemplars == []
        assert "没有叙事蓝图" in preset.content
        assert "没有金样本" in preset.content
        assert "references/narrative-blueprint.md" not in preset.content

    def test_dangling_component_id_is_reported_and_skipped(self, data_dir: Path) -> None:
        export = self._one(
            {"color_scheme": "c1", "animation_style": "gone"},
            [_component("c1", "color_scheme", "配色")],
        )

        report = import_export(data_dir, export)

        assert report.created == ["T"]
        assert any("悬空" in p and "gone" in p for p in report.problems)

    def test_empty_component_text_counts_as_missing(self, data_dir: Path) -> None:
        export = self._one(
            {"color_scheme": "c1", "animation_style": "a1"},
            [_component("c1", "color_scheme", "配色"), _component("a1", "animation_style", "   ")],
        )

        report = import_export(data_dir, export)

        assert any("animation_style" in p and "空" in p for p in report.problems)
        assert [f.name for f in list_style_presets(data_dir)[0].references] == ["color-scheme.md"]

    def test_component_of_the_wrong_category_is_not_used(self, data_dir: Path) -> None:
        export = self._one(
            {"color_scheme": "c1", "animation_style": "a1"},
            [_component("c1", "color_scheme", "配色"), _component("a1", "exemplar", "{}")],
        )

        report = import_export(data_dir, export)

        assert any("类别不符" in p and "a1" in p for p in report.problems)
        assert [f.name for f in list_style_presets(data_dir)[0].references] == ["color-scheme.md"]

    def test_template_with_nothing_usable_is_skipped_not_created(self, data_dir: Path) -> None:
        export = self._one({"color_scheme": "gone"}, [])

        report = import_export(data_dir, export)

        assert report.created == []
        assert report.skipped_unusable == ["T"]
        assert list_style_presets(data_dir) == []

    def test_template_with_blank_name_is_skipped(self, data_dir: Path) -> None:
        export = _full_export()
        export["templates"][0]["name"] = "  "

        report = import_export(data_dir, export)

        assert report.created == []
        assert any("名称" in p for p in report.problems)

    def test_template_config_of_the_wrong_shape_is_skipped(self, data_dir: Path) -> None:
        export = _full_export()
        export["templates"][0]["style_config"] = ["n1"]

        report = import_export(data_dir, export)

        assert report.created == []
        assert any("style_config" in p for p in report.problems)

    def test_unused_components_are_listed(self, data_dir: Path) -> None:
        export = _full_export()
        export["components"].append(_component("x1", "color_scheme", "没人用", name="孤儿配色"))

        report = import_export(data_dir, export)

        assert report.unused_components == ["孤儿配色"]


class TestIdempotence:
    def test_second_import_creates_nothing_and_reports_skips(self, data_dir: Path) -> None:
        import_export(data_dir, _full_export())

        report = import_export(data_dir, _full_export())

        assert report.created == []
        assert report.skipped_existing == ["概念传记·纸上溯源"]
        assert len(list_style_presets(data_dir)) == 1

    def test_user_edits_survive_a_reimport(self, data_dir: Path) -> None:
        import_export(data_dir, _full_export())
        preset = list_style_presets(data_dir)[0]
        update_category(data_dir, preset.id, "我的分类")

        import_export(data_dir, _full_export())

        got = get_style_preset(data_dir, preset.id)
        assert got is not None and got.category == "我的分类"

    def test_overwrite_replaces_the_files_of_the_same_named_preset(self, data_dir: Path) -> None:
        import_export(data_dir, _full_export())
        preset = list_style_presets(data_dir)[0]
        update_category(data_dir, preset.id, "我的分类")
        changed = _full_export()
        changed["components"][1]["prompt_text"] = "新配色"

        report = import_export(data_dir, changed, overwrite=True)

        assert report.overwritten == ["概念传记·纸上溯源"]
        got = get_style_preset(data_dir, preset.id)
        assert got is not None
        assert {f.name: f.text for f in got.references}["color-scheme.md"] == "新配色"
        assert len(list_style_presets(data_dir)) == 1

    def test_names_repeated_inside_one_export_import_only_the_first(self, data_dir: Path) -> None:
        export = _full_export()
        export["templates"].append(dict(export["templates"][0], id="t-dup"))

        report = import_export(data_dir, export)

        assert report.created == ["概念传记·纸上溯源"]
        assert report.skipped_existing == ["概念传记·纸上溯源"]


class TestLoadAndCli:
    def test_load_export_reads_a_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "styles.json"
        path.write_text(json.dumps(_full_export(), ensure_ascii=False), encoding="utf-8")

        assert load_export(path)["templates"][0]["name"] == "概念传记·纸上溯源"

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            "[]",
            json.dumps({"templates": []}),
            json.dumps({"templates": {}, "components": []}),
        ],
    )
    def test_malformed_export_is_a_clear_error(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / "styles.json"
        path.write_text(content, encoding="utf-8")

        with pytest.raises(LegacyExportError):
            load_export(path)

    def test_missing_file_is_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(LegacyExportError):
            load_export(tmp_path / "nope.json")

    def test_cli_imports_and_prints_a_report(
        self,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = tmp_path / "styles.json"
        path.write_text(json.dumps(_full_export(), ensure_ascii=False), encoding="utf-8")

        code = main(["import", str(path)], data_dir=data_dir)

        out = capsys.readouterr().out
        assert code == 0
        assert "新增 1" in out
        assert len(list_style_presets(data_dir)) == 1

    def test_cli_reports_a_bad_file_and_fails(
        self,
        data_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code = main(["import", str(tmp_path / "nope.json")], data_dir=data_dir)

        assert code == 1
        assert "nope.json" in capsys.readouterr().err
