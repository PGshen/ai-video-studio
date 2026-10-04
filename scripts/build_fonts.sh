#!/usr/bin/env bash
# 一次性开发期脚本：生成 HTML 引擎随包的 Noto Sans SC 子集（400/700）。
# 产物入库（backend/src/studio/engines/render/html/fonts/），运行时不依赖 fonttools。
#
# 用法：scripts/build_fonts.sh [NotoSansSC[wght].ttf 路径]
# 不传路径时从 Google Fonts 仓库下载可变字体（OFL）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/backend/src/studio/engines/render/html/fonts"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SRC="${1:-}"

if [[ -z "$SRC" ]]; then
  SRC="$WORK/NotoSansSC.ttf"
  curl -fsSL -o "$SRC" 'https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf'
  curl -fsSL -o "$OUT/OFL-NotoSansSC.txt" 'https://github.com/google/fonts/raw/main/ofl/notosanssc/OFL.txt'
fi

mkdir -p "$OUT"
cd "$ROOT/backend"
SRC="$SRC" OUT="$OUT" uv run --with fonttools --with brotli python - <<'PY'
import os
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

src, out = Path(os.environ["SRC"]), Path(os.environ["OUT"])

chars: set[str] = {chr(c) for c in range(0x20, 0x7F)}
# GB2312：A1-A9 区符号，B0-F7 区一二级汉字。
for row in list(range(0xA1, 0xAA)) + list(range(0xB0, 0xF8)):
    for col in range(0xA1, 0xFF):
        try:
            chars.add(bytes([row, col]).decode("gb2312"))
        except UnicodeDecodeError:
            pass
chars.update("←↑→↓↔⇒⇐⇔×÷±≈≠≤≥∞√∑∏∫∂∆π°′″‰²³⁴⁵⁶⁷⁸⁹⁰¹₀₁₂₃₄₅₆₇₈₉①②③④⑤⑥⑦⑧⑨⑩ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ")
chars.update("—…·•“”‘’《》〈〉「」『』【】★☆●○■□▲△▼▽◆◇✓✗✔✘♪♫")

opts = subset.Options()
opts.flavor = "woff2"
opts.layout_features = ["*"]
opts.notdef_outline = True
opts.name_IDs = ["*"]

covered: set[str] = set()
for weight in (400, 700):
    font = TTFont(src)
    instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(sorted(chars)))
    sub.subset(font)
    target = out / f"notosanssc-{weight}.woff2"
    font.flavor = "woff2"
    font.save(target)
    cmap = TTFont(target).getBestCmap()
    covered |= {chr(cp) for cp in cmap}
    print(f"{target.name}: {target.stat().st_size / 1e6:.2f} MB, {len(cmap)} glyphs")

(out / "coverage.txt").write_text("".join(sorted(covered)), encoding="utf-8")
print(f"coverage.txt: {len(covered)} chars")
PY
