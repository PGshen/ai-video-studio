#!/usr/bin/env bash
# make dev 的实现：启动 api、worker、前端三个进程。
# uvicorn 的 --reload-dir 只指向 backend/src，工作区（data/）不在监听范围内
# （AGENTS.md 红线：工作区不能被 uvicorn reload 监听到）；worker 不需要热重载，
# 不接 --reload（M2 T5）。
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

# 每个后台任务单独一个进程组（set -m），退出时整组结束：uvicorn --reload 的 reloader
# 和它派生的 server 子进程、`uv run` 派生的 python、`pnpm run dev` 派生的 vite 都在组里，
# 只 kill 顶层 pid 会留下孤儿进程，下次启动就是"端口被占用"。
#
# 副作用：这些进程组都成了终端的后台进程组，任何一个进程读/配置终端（ffmpeg 默认会
# 读 stdin）都会收到 SIGTTIN/SIGTTOU，内核把整组停住，API 就整体冻死。所以下面每个
# 后台任务都必须 `</dev/null`，不能让它们碰到终端 stdin。
set -m
pids=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do
    # 先 CONT：被停住（T 状态）的进程收不到 TERM，不唤醒就清理不掉。
    kill -CONT -- "-$pid" 2>/dev/null || true
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ---- 启动前清理上一次遗留的本项目进程 ----

# 进程的当前工作目录（macOS 和 Linux 的 lsof 都支持）。
proc_cwd() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

# 判断 pid 是否属于本项目：工作目录在仓库内，或命令行里带有仓库路径。
is_project_proc() {
  local cwd cmd
  cwd="$(proc_cwd "$1")"
  case "$cwd" in "$ROOT_DIR"|"$ROOT_DIR"/*) return 0 ;; esac
  cmd="$(ps -o command= -p "$1" 2>/dev/null || true)"
  case "$cmd" in *"$ROOT_DIR"*) return 0 ;; esac
  return 1
}

# 本脚本自己的祖先进程（make、shell 等），绝不能误杀。
own_ancestors=" "
_p=$$
while [ -n "$_p" ] && [ "$_p" -gt 1 ]; do
  own_ancestors="$own_ancestors$_p "
  _p="$(ps -o ppid= -p "$_p" 2>/dev/null | tr -d ' ')"
done

is_own_ancestor() {
  case "$own_ancestors" in *" $1 "*) return 0 ;; esac
  return 1
}

# 向上收集属于本项目的父进程：uvicorn --reload 的 reloader 在 server 子进程被杀后
# 会立刻重新拉起它，所以必须连父进程一起结束。
with_project_ancestors() {
  local pid="$1" parent
  echo "$pid"
  parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
  while [ -n "$parent" ] && [ "$parent" -gt 1 ] && ! is_own_ancestor "$parent" && is_project_proc "$parent"; do
    echo "$parent"
    parent="$(ps -o ppid= -p "$parent" 2>/dev/null | tr -d ' ')"
  done
}

# 结束一批 pid：先 TERM，最多等 5 秒，仍存活的再 KILL。
terminate_pids() {
  local pid i alive
  [ "$#" -gt 0 ] || return 0
  kill -CONT "$@" 2>/dev/null || true # 被停住的进程要先唤醒才能响应 TERM
  kill "$@" 2>/dev/null || true
  for i in 1 2 3 4 5 6 7 8 9 10; do
    alive=0
    for pid in "$@"; do
      if kill -0 "$pid" 2>/dev/null; then alive=1; fi
    done
    [ "$alive" -eq 0 ] && return 0
    sleep 0.5
  done
  kill -9 "$@" 2>/dev/null || true
}

# 释放端口：占用者属于本项目就结束它；不属于本项目则报错退出，不动别人的进程。
free_port() {
  local port="$1" label="$2" pid listeners v victims=()
  listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
  [ -n "$listeners" ] || return 0
  for pid in $listeners; do
    if is_project_proc "$pid"; then
      while read -r v; do victims+=("$v"); done < <(with_project_ancestors "$pid")
    else
      echo "端口 $port（$label）被非本项目的进程占用，未处理：" >&2
      ps -o pid=,command= -p "$pid" >&2 || true
      echo "请手动结束它，或修改端口配置。" >&2
      exit 1
    fi
  done
  echo "清理占用 $label 端口 $port 的旧进程：${victims[*]}"
  terminate_pids "${victims[@]}"
}

# 上一次遗留的 worker 不监听端口，按命令行识别；多个 worker 会重复抢任务。
kill_stale_workers() {
  local pid victims=()
  for pid in $(pgrep -f 'studio\.worker' 2>/dev/null || true); do
    is_own_ancestor "$pid" && continue
    [ "$pid" = "$$" ] && continue
    is_project_proc "$pid" && victims+=("$pid")
  done
  [ "${#victims[@]}" -gt 0 ] || return 0
  echo "清理遗留的 worker 进程：${victims[*]}"
  terminate_pids "${victims[@]}"
}

if [ -f "$ROOT_DIR/backend/pyproject.toml" ]; then
  # 绑定地址从 Settings 读取（`studio.config` 的 `__main__` 输出 "host port"），
  # 而不是在这里写死，否则改 STUDIO_HOST/STUDIO_PORT 不会真的生效（TD-2）。
  # process substitution 会掩盖 studio.config 失败：`read` 读不到内容时只是返回
  # 非零，`set -e` 会让脚本直接终止、只留下 Python traceback，所以显式检查
  # `read` 的结果并给出清晰的错误（TD-30）。
  if ! read -r STUDIO_BIND_HOST STUDIO_BIND_PORT < <(cd "$ROOT_DIR/backend" && "$UV" run python -m studio.config); then
    echo "无法从 'python -m studio.config' 读取绑定地址，请检查上面是否有报错" >&2
    exit 1
  fi
  # 导出给下面的前端进程：vite.config.ts 读它来生成 dev-server 代理目标
  # （TD-2 未覆盖到的部分，复核发现）。
  export STUDIO_BIND_PORT
  free_port "$STUDIO_BIND_PORT" "api"
  kill_stale_workers
  (
    cd "$ROOT_DIR/backend"
    exec "$UV" run uvicorn studio.main:app \
      --reload \
      --reload-dir "$ROOT_DIR/backend/src" \
      --host "$STUDIO_BIND_HOST" \
      --port "$STUDIO_BIND_PORT"
  ) </dev/null &
  pids+=("$!")
  echo "api: http://$STUDIO_BIND_HOST:$STUDIO_BIND_PORT (OpenAPI: /docs)"

  (
    cd "$ROOT_DIR/backend"
    exec "$UV" run python -m studio.worker
  ) </dev/null &
  pids+=("$!")
  echo "worker: 已启动（成片渲染任务循环，日志见上方 [worker] 前缀）"
else
  echo "跳过后端启动：backend/ 尚未创建"
fi

if [ -f "$ROOT_DIR/frontend/package.json" ]; then
  # vite.config.ts 设了 strictPort，5173 被占用时会直接退出。
  free_port 5173 "frontend"
  (
    cd "$ROOT_DIR/frontend"
    exec "$PNPM" run dev
  ) </dev/null &
  pids+=("$!")
  echo "frontend: http://127.0.0.1:5173"
else
  echo "跳过前端启动：frontend/ 尚未创建"
fi

wait
