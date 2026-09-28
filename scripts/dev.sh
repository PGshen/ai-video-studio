#!/usr/bin/env bash
# make dev 的实现：启动 api 和前端（worker 留到 M2）。
# uvicorn 的 --reload-dir 只指向 backend/src，工作区（data/）不在监听范围内
# （AGENTS.md 红线：工作区不能被 uvicorn reload 监听到）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Claude Code 沙箱的 PATH 可能不包含 ~/.local/bin 和 nvm shims，这里主动定位（同 Makefile）。
UV="${UV:-$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")}"
PNPM="${PNPM:-$(command -v pnpm 2>/dev/null || ls -d "$HOME"/.nvm/versions/node/*/bin/pnpm 2>/dev/null | tail -1)}"

# 模型 key 由各运行时从 os.environ 按模型配置的 api_key_env 读取，而 pydantic-settings
# 只把 backend/.env 读进 Settings 字段、不写进 os.environ，所以这里整体导出。
if [ -f "$ROOT_DIR/backend/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/backend/.env"
  set +a
fi

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
  # 绑定地址从 Settings 读取（`studio.config` 的 `__main__` 输出 "host port"），
  # 而不是在这里写死，否则改 STUDIO_HOST/STUDIO_PORT 不会真的生效（TD-2）。
  read -r STUDIO_BIND_HOST STUDIO_BIND_PORT < <(cd "$ROOT_DIR/backend" && "$UV" run python -m studio.config)
  # process substitution 会掩盖 studio.config 失败：read 只是读不到内容而不
  # 报错，uvicorn 随后才因为空 host/port 报出一堆无关的错误，这里先显式检查。
  if [ -z "$STUDIO_BIND_HOST" ] || [ -z "$STUDIO_BIND_PORT" ]; then
    echo "无法从 'python -m studio.config' 读取绑定地址，请检查上面是否有报错" >&2
    exit 1
  fi
  # 导出给下面的前端进程：vite.config.ts 读它来生成 dev-server 代理目标
  # （TD-2 未覆盖到的部分，复核发现）。
  export STUDIO_BIND_PORT
  (
    cd "$ROOT_DIR/backend"
    exec "$UV" run uvicorn studio.main:app \
      --reload \
      --reload-dir "$ROOT_DIR/backend/src" \
      --host "$STUDIO_BIND_HOST" \
      --port "$STUDIO_BIND_PORT"
  ) &
  pids+=("$!")
  echo "api: http://$STUDIO_BIND_HOST:$STUDIO_BIND_PORT (OpenAPI: /docs)"
else
  echo "跳过后端启动：backend/ 尚未创建"
fi

if [ -f "$ROOT_DIR/frontend/package.json" ]; then
  (
    cd "$ROOT_DIR/frontend"
    exec "$PNPM" run dev
  ) &
  pids+=("$!")
  echo "frontend: http://127.0.0.1:5173"
else
  echo "跳过前端启动：frontend/ 尚未创建"
fi

wait
