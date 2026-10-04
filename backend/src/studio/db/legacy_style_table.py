"""一次性迁移：旧 `style_presets` 表 → 磁盘目录（ADR 0019；计划 style-library T4）。

由迁移 0007 调用，导出成功后才删表；用原生 SQL 读旧表，不依赖 ORM 模型（模型随旧表一起删除）。

- 目录名沿用旧 id，`default_style_preset_id` 和各项目记录的 `style_preset_id` 因此不用重新映射；
- 名称、简介、分类以数据库列为准写进 `STYLE.md` 的 frontmatter（旧行可能没有 frontmatter，
  也可能与列不一致——界面上显示的是列），正文保持原样；
- 目录已存在就跳过，重复执行不会覆盖用户后来的改动；
- 不合法或重名的行逐条记入报告并最终抛 `StyleTableExportError`（其余行照常导出），
  由迁移失败来阻止删表，数据修好后重新迁移即可。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Connection, inspect, text

from studio.styles import store
from studio.styles.layout import ENTRY_NAME, is_valid_style_id, style_dir
from studio.styles.validate import StyleFiles, parse_frontmatter, set_frontmatter_fields

_TABLE: Final = "style_presets"
_FALLBACK_DESCRIPTION: Final = "从旧版风格库迁移（原风格没有填写简介）"


@dataclass(slots=True)
class ExportReport:
    exported: list[str] = field(default_factory=list)
    """导出的风格 id。"""
    skipped_existing: list[str] = field(default_factory=list)
    """目录已存在而跳过的风格 id。"""
    synthesized_frontmatter: list[str] = field(default_factory=list)
    """frontmatter 缺失或与列不一致、按列补写了名称/简介的风格名称。"""
    problems: list[str] = field(default_factory=list)


class StyleTableExportError(RuntimeError):
    """有行没能导出；`report` 里逐条列出问题。"""

    def __init__(self, report: ExportReport) -> None:
        super().__init__("旧风格表导出失败，旧表保留：" + "；".join(report.problems))
        self.report = report


def _named_files(raw: Any, what: str) -> list[tuple[str, str]]:
    items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    result: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError(f"{what} 的条目格式不对")
        result.append((item["name"], str(item.get("text", ""))))
    return result


def _files_of(row: Any) -> tuple[StyleFiles, bool]:
    """旧行 → 目录内容；第二个返回值表示是否按列补写/改写了名称或简介。"""
    content = str(row["content"] or "")
    meta = parse_frontmatter(content) or {}
    wanted = {
        "name": (row["name"] or "").strip(),
        "description": (row["description"] or "").strip()
        or meta.get("description", "").strip()
        or _FALLBACK_DESCRIPTION,
        "category": (row["category"] or "").strip() or store.UNCATEGORIZED,
    }
    changed = {key: value for key, value in wanted.items() if meta.get(key, "").strip() != value}
    if changed:
        content = set_frontmatter_fields(content, changed)
    files: StyleFiles = {ENTRY_NAME: content}
    for name, body in _named_files(row["reference_files"], "reference_files"):
        files[f"references/{name}"] = body
    for name, body in _named_files(row["exemplars"], "exemplars"):
        files[f"exemplars/{name}"] = body
    return files, "name" in changed or "description" in changed


def export_style_table(connection: Connection, data_dir: Path | None) -> ExportReport:
    """把旧表的每一行导出成 `<data_dir>/styles/<id>/`；表不存在则什么都不做。"""
    report = ExportReport()
    if not inspect(connection).has_table(_TABLE):
        return report
    rows = (
        connection.execute(
            text(
                "SELECT id, name, category, content, description, reference_files, exemplars "
                f"FROM {_TABLE} ORDER BY created_at, id"
            )
        )
        .mappings()
        .all()
    )
    if rows and data_dir is None:
        report.problems.append("无法确定数据目录（数据库不是文件），旧表里还有风格没有导出")
        raise StyleTableExportError(report)
    for row in rows:
        assert data_dir is not None
        _export_row(row, data_dir, report)
    if report.problems:
        raise StyleTableExportError(report)
    return report


def _export_row(row: Any, data_dir: Path, report: ExportReport) -> None:
    style_id = str(row["id"])
    label = (row["name"] or "").strip() or style_id
    if not is_valid_style_id(style_id):
        report.problems.append(f"风格「{label}」的 id 不能用作目录名：{style_id!r}")
        return
    if style_dir(data_dir, style_id).exists():
        report.skipped_existing.append(style_id)
        return
    try:
        files, fixed = _files_of(row)
        store.import_style(data_dir, files, style_id=style_id)
    except store.StyleValidationError as exc:
        report.problems.append(f"风格「{label}」不合法：{exc}")
    except store.DuplicateStyleNameError:
        report.problems.append(f"风格「{label}」与已有风格重名，没有导出")
    except (ValueError, TypeError) as exc:
        report.problems.append(f"风格「{label}」的数据无法读取：{exc}")
    else:
        report.exported.append(style_id)
        if fixed:
            report.synthesized_frontmatter.append(label)
