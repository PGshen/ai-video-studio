"""跨阶段共享的提示词片段（free-mode 设计 §4.4）。

片段是从某个阶段原有提示词里切出的连续段落（以 `## ` 标题为界），只描述格式、契约与引擎规则；
与阶段绑定的说法（读 `upstream/…`、"只能写 X"）留在各阶段自己的段落里。拼接是直接首尾相连，
每个文件自带结尾的空行，所以多阶段提示词拼出来与拆分前逐字相同。
"""

from __future__ import annotations

from pathlib import Path

FRAGMENTS_DIR = Path(__file__).parent


def fragment(name: str) -> Path:
    """共享片段 `<name>.md` 的路径；不存在时抛 `ValueError`（拼错片段名应当立刻暴露）。"""
    path = FRAGMENTS_DIR / f"{name}.md"
    if not path.is_file():
        raise ValueError(f"未知的提示词片段：{name}")
    return path


def compose_prompt(*parts: Path) -> str:
    """按顺序读出各段并首尾相连。"""
    return "".join(part.read_text(encoding="utf-8") for part in parts)
