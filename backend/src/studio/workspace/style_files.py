"""风格预设 → 工作区 `style/` 目录的文件映射（决策 D1；计划 M5 T2）。

纯函数，不读写磁盘；结果交给 `workspace.files.init_workspace` 写入。路径安全由预设的校验
（`db.repo.style_presets.validate_style_preset`：文件名只允许普通字符）和 `init_workspace`
里的 `safe_path` 共同保证。
"""

from __future__ import annotations

from studio.db.repo.style_presets import StylePresetValue

STYLE_ENTRY_PATH = "style/STYLE.md"


def render_style_files(preset: StylePresetValue) -> dict[str, str]:
    """`{工作区相对路径: 文本}`：入口、`references/*`、`exemplars/*`，按预设里的顺序。"""
    files = {STYLE_ENTRY_PATH: preset.content}
    for reference in preset.references:
        files[f"style/references/{reference.name}"] = reference.text
    for exemplar in preset.exemplars:
        files[f"style/exemplars/{exemplar.name}"] = exemplar.text
    return files
