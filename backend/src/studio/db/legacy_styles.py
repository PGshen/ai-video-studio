"""旧项目风格库导入（计划 M5 T4，决策 D2）。

输入是 `scripts/export_legacy_styles.sh` 从旧项目 Postgres 只读导出的 JSON：
`{"templates": [...], "components": [...]}`。旧库里一套风格由 `style_templates` 的
`style_config` 把四个类别映射到 `prompt_components` 的 id：

| 旧类别 | 新位置 |
|---|---|
| `narrative_style`（叙事蓝图） | `references/narrative-blueprint.md` |
| `color_scheme`（配色） | `references/color-scheme.md` |
| `animation_style`（动画风格） | `references/animation-style.md` |
| `exemplar`（金样本） | `exemplars/exemplar-1.json`（内容不是合法 JSON 时 `.md`） |

每个模板 → 一条预设；组件正文**原样**落盘，不改写。入口 `STYLE.md` 由程序生成：frontmatter、
简介、文件索引（每个文件什么时候读，与三个阶段的提示词一致）、缺失项和「旧格式」提示。
缺类别、组件 id 悬空、文本为空、类别不符都不阻止导入（报告里列出）；一个可用组件都没有的
模板才跳过。按名字幂等：同名预设默认跳过（保护使用者在界面里的修改），`--overwrite` 才覆盖。

用法：`python -m studio.db.legacy_styles import <export.json> [--overwrite]`
（`make import-legacy-styles FILE=...`）。旧代码不 import，只读导出的 JSON。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Engine

from studio.db.repo.style_presets import (
    DuplicateStylePresetError,
    StyleFile,
    StylePresetValidationError,
    create_style_preset,
    list_style_preset_summaries,
    update_style_preset,
)

IMPORT_CATEGORY: Final = "旧项目导入"

# 配色两个阶段都要读：叙事阶段写 visual_intent/visual_action 要带上颜色，动画阶段写代码要用色值。
_COLOR_SCHEME_WHEN: Final = (
    "叙事阶段：动笔改 `narrative.json` 之前（画面描述要写明颜色）；动画阶段：写镜头代码之前"
)

# 旧类别 → (新文件名, 中文名, 什么时候读)
_REFERENCE_CATEGORIES: Final = (
    (
        "narrative_style",
        "narrative-blueprint.md",
        "叙事蓝图",
        "叙事阶段：动笔改 `narrative.json` 之前",
    ),
    ("color_scheme", "color-scheme.md", "配色方案", _COLOR_SCHEME_WHEN),
    ("animation_style", "animation-style.md", "动画风格", "动画阶段：写镜头代码之前"),
)
_EXEMPLAR_CATEGORY: Final = "exemplar"
_EXEMPLAR_WHEN: Final = "叙事阶段：动笔改 `narrative.json` 之前"
_KNOWN_CATEGORIES: Final = {c[0] for c in _REFERENCE_CATEGORIES} | {_EXEMPLAR_CATEGORY}
_MISSING_LABELS: Final = {
    "narrative_style": "叙事蓝图",
    "color_scheme": "配色方案",
    "animation_style": "动画风格",
    "exemplar": "金样本",
}
_LEGACY_FIELDS: Final = re.compile(r"scene_index|beat_index|estimated_duration")
_FALLBACK_DESCRIPTION: Final = "从旧项目导入的风格模板（原模板没有填写描述）"


class LegacyExportError(ValueError):
    """导出文件读不了或结构不对。"""


@dataclass(slots=True)
class ImportReport:
    created: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    skipped_unusable: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    unused_components: list[str] = field(default_factory=list)
    legacy_format_exemplars: list[str] = field(default_factory=list)
    legacy_field_blueprints: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Converted:
    name: str
    description: str
    content: str
    references: list[StyleFile]
    exemplars: list[StyleFile]
    legacy_exemplar: bool
    legacy_blueprint: bool


# ---- 读取导出文件 ---------------------------------------------------------


def load_export(path: Path) -> dict[str, Any]:
    """读并检查导出 JSON 的外层结构；不对时抛 `LegacyExportError`。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LegacyExportError(f"无法读取 {path}：{exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise LegacyExportError(f"{path} 不是合法的 JSON：{exc}") from exc
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("templates"), list)
        or not isinstance(data.get("components"), list)
    ):
        raise LegacyExportError(f"{path} 的结构不对：需要 {{templates: [...], components: [...]}}")
    return data


# ---- 转换 -----------------------------------------------------------------


def _yaml_scalar(text: str) -> str:
    """单行 frontmatter 值：折叠空白；含特殊字符时用双引号包起来并转义。"""
    flat = " ".join(text.split())
    if flat and not any(ch in flat for ch in ':#"\\') and flat[0] not in "-?[]{}&*!|>'%@`":
        return flat
    return '"' + flat.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_legacy_scene_format(text: str) -> bool:
    """金样本是不是旧系统的镜头格式（`scene_index`），与新叙事产物（稳定 `id`）不同。"""
    try:
        doc = json.loads(text)
    except ValueError:
        return False
    scenes = doc.get("scenes") if isinstance(doc, dict) else None
    return isinstance(scenes, list) and any(
        isinstance(scene, dict) and "scene_index" in scene for scene in scenes
    )


def _mentions_legacy_fields(text: str) -> bool:
    """叙事蓝图是否提到旧系统的镜头字段名（新 `narrative.json` 用的是另一套字段）。"""
    return _LEGACY_FIELDS.search(text) is not None


def _entry(
    name: str,
    description: str,
    present: dict[str, str],
    exemplar_file: str | None,
    legacy_files: list[str],
) -> str:
    """入口 `STYLE.md`：只索引真正存在的文件，缺失项单独说明。"""
    lines = [
        "---",
        f"name: {_yaml_scalar(name)}",
        f"description: {_yaml_scalar(description)}",
        "---",
        "",
        f"# {name}",
        "",
        description,
        "",
        f"这套风格从旧项目的风格模板「{name}」导入。下面列出每个文件的用途和读取时机；",
        "选题阶段只需要读本文件。",
        "",
        "| 文件 | 内容 | 什么时候读 |",
        "|---|---|---|",
    ]
    for category, file_name, label, when in _REFERENCE_CATEGORIES:
        if category in present:
            lines.append(f"| `references/{file_name}` | {label} | {when} |")
    if exemplar_file is not None:
        lines.append(
            f"| `exemplars/{exemplar_file}` | 金样本（镜头结构与旁白语感） | {_EXEMPLAR_WHEN} |"
        )
    missing = [
        _MISSING_LABELS[c]
        for c in ("narrative_style", "color_scheme", "animation_style", "exemplar")
        if c not in present
    ]
    if missing:
        lines += ["", "**缺失**：" + "、".join(f"这套风格没有{label}" for label in missing) + "。"]
    if legacy_files:
        listed = "、".join(f"`{path}`" for path in legacy_files)
        lines += [
            "",
            f"**旧格式提示**：{listed} 沿用了旧系统的镜头字段名"
            "（`scene_index`、`beat_index`、`description`、`estimated_duration_seconds` 等）。"
            "`narrative.json` 的字段一律以叙事阶段的系统提示词为准；这些文件只参考写法、"
            "旁白语感、信息密度和镜头节奏，不要照抄字段名。",
        ]
    return "\n".join(lines) + "\n"


def _convert_template(
    template: dict[str, Any],
    components: dict[str, dict[str, Any]],
    problems: list[str],
    used_ids: set[str],
) -> _Converted | None:
    name = str(template.get("name") or "").strip()
    if not name:
        problems.append(f"有一个模板的名称为空（id {template.get('id')}），已跳过")
        return None
    config = template.get("style_config")
    if not isinstance(config, dict):
        problems.append(f"模板「{name}」的 style_config 不是对象，已跳过")
        return None

    present: dict[str, str] = {}
    for category, component_id in config.items():
        if category not in _KNOWN_CATEGORIES:
            problems.append(f"模板「{name}」的 style_config 有未知类别 {category}，已忽略")
            continue
        used_ids.add(str(component_id))
        component = components.get(str(component_id))
        if component is None:
            problems.append(
                f"模板「{name}」的 {category} 引用了不存在的组件 {component_id}（悬空 id）"
            )
        elif component.get("category") != category:
            problems.append(
                f"模板「{name}」的 {category} 引用的组件 {component_id} 类别不符"
                f"（实际是 {component.get('category')}）"
            )
        elif not str(component.get("prompt_text") or "").strip():
            problems.append(f"模板「{name}」的 {category} 组件文本为空")
        else:
            present[category] = str(component["prompt_text"])
    for category in _KNOWN_CATEGORIES - set(config):
        problems.append(f"模板「{name}」缺少 {category}（旧项目里没有配置）")

    if not present:
        problems.append(f"模板「{name}」没有任何可用的组件，已跳过")
        return None

    references = [
        StyleFile(file_name, present[category])
        for category, file_name, _label, _when in _REFERENCE_CATEGORIES
        if category in present
    ]
    exemplars: list[StyleFile] = []
    legacy_files: list[str] = []
    legacy_blueprint = "narrative_style" in present and _mentions_legacy_fields(
        present["narrative_style"]
    )
    if legacy_blueprint:
        legacy_files.append("references/narrative-blueprint.md")
    legacy_exemplar = False
    if _EXEMPLAR_CATEGORY in present:
        text = present[_EXEMPLAR_CATEGORY]
        try:
            json.loads(text)
            exemplars.append(StyleFile("exemplar-1.json", text))
        except ValueError:
            exemplars.append(StyleFile("exemplar-1.md", text))
        legacy_exemplar = _is_legacy_scene_format(text)
        if legacy_exemplar:
            legacy_files.append(f"exemplars/{exemplars[0].name}")
    description = " ".join(str(template.get("description") or "").split()) or _FALLBACK_DESCRIPTION
    return _Converted(
        name=name,
        description=description,
        content=_entry(
            name, description, present, exemplars[0].name if exemplars else None, legacy_files
        ),
        references=references,
        exemplars=exemplars,
        legacy_exemplar=legacy_exemplar,
        legacy_blueprint=legacy_blueprint,
    )


# ---- 导入 -----------------------------------------------------------------


def import_export(
    engine: Engine, export: dict[str, Any], *, overwrite: bool = False
) -> ImportReport:
    """把导出内容写进风格库，返回报告。同名预设默认跳过，`overwrite` 时覆盖它的内容和文件。"""
    report = ImportReport()
    components = {str(c.get("id")): c for c in export["components"] if isinstance(c, dict)}
    existing = {p.name.strip(): p.id for p in list_style_preset_summaries(engine)}
    used_ids: set[str] = set()
    handled: set[str] = set()

    templates = sorted(
        (t for t in export["templates"] if isinstance(t, dict)),
        key=lambda t: str(t.get("name") or ""),
    )
    for template in templates:
        converted = _convert_template(template, components, report.problems, used_ids)
        if converted is None:
            report.skipped_unusable.append(str(template.get("name") or "").strip() or "（无名）")
            continue
        name = converted.name
        try:
            if name in handled or (name in existing and not overwrite):
                report.skipped_existing.append(name)
                continue
            if name in existing:
                update_style_preset(
                    engine,
                    existing[name],
                    description=converted.description,
                    content=converted.content,
                    references=converted.references,
                    exemplars=converted.exemplars,
                )
                report.overwritten.append(name)
            else:
                created = create_style_preset(
                    engine,
                    name=name,
                    category=IMPORT_CATEGORY,
                    description=converted.description,
                    content=converted.content,
                    references=converted.references,
                    exemplars=converted.exemplars,
                )
                existing[name] = created.id
                report.created.append(name)
            handled.add(name)
            if converted.legacy_exemplar:
                report.legacy_format_exemplars.append(name)
            if converted.legacy_blueprint:
                report.legacy_field_blueprints.append(name)
        except StylePresetValidationError as exc:
            report.problems.append(f"模板「{name}」转换后没有通过风格校验：{exc}")
            report.skipped_unusable.append(name)
        except DuplicateStylePresetError:
            report.skipped_existing.append(name)

    report.unused_components = sorted(
        str(c.get("name") or c.get("id")) for cid, c in components.items() if cid not in used_ids
    )
    return report


# ---- 命令行 ---------------------------------------------------------------


def _print_report(report: ImportReport) -> None:
    print(
        f"导入完成：新增 {len(report.created)}，跳过（已存在）{len(report.skipped_existing)}，"
        f"覆盖 {len(report.overwritten)}，无法导入 {len(report.skipped_unusable)}"
    )
    for label, names in (
        ("新增", report.created),
        ("跳过（已存在）", report.skipped_existing),
        ("覆盖", report.overwritten),
        ("无法导入", report.skipped_unusable),
        ("金样本是旧格式", report.legacy_format_exemplars),
        ("叙事蓝图提到旧字段名", report.legacy_field_blueprints),
        ("没有被任何模板引用的组件", report.unused_components),
    ):
        if names:
            print(f"{label}：" + "、".join(names))
    if report.problems:
        print(f"问题（共 {len(report.problems)} 条）：")
        for problem in report.problems:
            print(f"  - {problem}")


def main(argv: list[str] | None = None, *, engine: Engine | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m studio.db.legacy_styles")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="把旧项目导出的风格 JSON 导入风格库")
    imp.add_argument("file", type=Path)
    imp.add_argument("--overwrite", action="store_true", help="同名预设也覆盖（默认跳过）")
    args = parser.parse_args(argv)

    try:
        export = load_export(args.file)
    except LegacyExportError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if engine is None:
        from studio.config import get_settings
        from studio.db.engine import make_engine, migrate

        engine = make_engine(get_settings().data_dir / "studio.db")
        migrate(engine)
    _print_report(import_export(engine, export, overwrite=args.overwrite))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
