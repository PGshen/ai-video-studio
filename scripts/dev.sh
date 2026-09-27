#!/usr/bin/env bash
# make dev 的实现：启动 api（和前端，T11 接入）。
# uvicorn 的 --reload-dir 只指向 backend/src，工作区（data/）不在监听范围内
# （AGENTS.md 红线：工作区不能被 uvicorn reload 监听到）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Claude Code 沙箱的 PATH 可能不包含 ~/.local/bin，这里主动定位（同 Makefile）。
UV="${UV:-$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")}"

pids=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ -f "$ROOT_DIR/backend/pyproject.toml" ]; then
  (
    cd "$ROOT_DIR/backend"
    exec "$UV" run uvicorn studio.main:app \
      --reload \
      --reload-dir "$ROOT_DIR/backend/src" \
      --host 127.0.0.1 \
      --port 8000
  ) &
  pids+=("$!")
  echo "api: http://127.0.0.1:8000 (OpenAPI: /docs)"
else
  echo "跳过后端启动：backend/ 尚未创建"
fi

# TODO(T11): frontend/ 就位后在这里同时启动 `pnpm dev`。

wait
