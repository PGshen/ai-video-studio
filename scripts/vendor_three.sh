#!/usr/bin/env bash
# 一次性开发期脚本：把固定版本的 three.js 核心打成一个经典脚本（IIFE，定义全局 THREE），放进
# HTML 引擎（ADR 0028）。产物入库（backend/src/studio/engines/render/html/vendor/），运行时不依赖 npm。
#
# three 自 r18x 起 build/three.cjs 只是转发到 ES module 的薄壳，所以用前端已有的 vite（库模式、
# iife 格式）把 build/three.module.js 打包；不引入新工具。需要先在 frontend/ 里 pnpm install。
#
# 用法：scripts/vendor_three.sh [版本]   默认 0.186.1
# 升级版本属于依赖升级：之后要重跑金样本与确定性测试，并升级 worker_html.ENGINE_VERSION。
set -euo pipefail

VERSION="${1:-0.186.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/backend/src/studio/engines/render/html/vendor"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

(cd "$WORK" && npm pack --silent "three@$VERSION" >/dev/null)
tar -xzf "$WORK/three-$VERSION.tgz" -C "$WORK"

mkdir -p "$OUT"
(cd "$ROOT/frontend" && ENTRY="$WORK/package/build/three.module.js" OUTDIR="$WORK/dist" \
  node --input-type=module -e '
import { build } from "vite";
await build({
  configFile: false,
  logLevel: "warn",
  build: {
    lib: { entry: process.env.ENTRY, formats: ["iife"], name: "THREE", fileName: () => "three.iife.js" },
    outDir: process.env.OUTDIR,
    emptyOutDir: true,
    minify: true,
    target: "es2020",
  },
});
')
cp "$WORK/dist/three.iife.js" "$OUT/three.iife.js"
cp "$WORK/package/LICENSE" "$OUT/three.LICENSE"
printf '%s\n' "$VERSION" > "$OUT/THREE_VERSION"
rm -f "$OUT/three.cjs"
echo "three@$VERSION -> $OUT"
