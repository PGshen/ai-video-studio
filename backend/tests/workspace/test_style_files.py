"""`render_style_files`（计划 M5 T2）：风格预设 → 工作区 `style/` 下的文件映射。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio.db.repo.style_presets import StyleFile, StylePresetValue
from studio.workspace import init_workspace, list_tree
from studio.workspace.style_files import render_style_files


def _preset(**overrides: Any) -> StylePresetValue:
    fields: dict[str, Any] = {
        "id": "p1",
        "name": "暖纸双色",
        "category": "概念传记",
        "description": "d",
        "content": "---\nname: n\ndescription: d\n---\n入口",
        "references": [
            StyleFile("color-scheme.md", "配色"),
            StyleFile("animation-style.md", "动画"),
        ],
        "exemplars": [StyleFile("exemplar-1.json", "{}")],
        "created_at": datetime(2026, 9, 30, tzinfo=UTC),
    }
    fields.update(overrides)
    return StylePresetValue(**fields)


def test_renders_entry_references_and_exemplars() -> None:
    files = render_style_files(_preset())

    assert files == {
        "style/STYLE.md": "---\nname: n\ndescription: d\n---\n入口",
        "style/references/color-scheme.md": "配色",
        "style/references/animation-style.md": "动画",
        "style/exemplars/exemplar-1.json": "{}",
    }


def test_preset_without_extra_files_renders_only_the_entry() -> None:
    files = render_style_files(_preset(references=[], exemplars=[]))

    assert list(files) == ["style/STYLE.md"]


def test_rendered_files_can_be_written_into_a_workspace(tmp_path: Path) -> None:
    init_workspace(tmp_path, "proj", render_style_files(_preset()))

    workdir = tmp_path / "projects" / "proj"
    assert list_tree(workdir) == [
        "style/STYLE.md",
        "style/exemplars/exemplar-1.json",
        "style/references/animation-style.md",
        "style/references/color-scheme.md",
    ]
    assert (workdir / "style" / "references" / "color-scheme.md").read_text(
        encoding="utf-8"
    ) == "配色"
