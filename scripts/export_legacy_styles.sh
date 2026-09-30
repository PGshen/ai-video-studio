#!/usr/bin/env bash
# 从旧项目（../ai-video）的 Postgres 只读导出风格库，供 `make import-legacy-styles` 导入
# （计划 M5 T4）。
#
# 只读：psql 会话设为 default_transaction_read_only，只执行一条 SELECT；不修改旧项目的任何
# 文件，也不 import 旧代码。库名和用户名从旧项目的 docker-compose.yml 读取（不是密钥；
# 容器内 psql 走本地套接字，不需要密码）。旧项目的 postgres 容器必须已经在运行：
#   cd ../ai-video && docker compose up -d postgres
#
# 用法：scripts/export_legacy_styles.sh [输出文件]     默认 data/legacy-export/styles.json
# 环境变量：LEGACY_COMPOSE_FILE（默认 ../ai-video/docker-compose.yml）、LEGACY_PG_SERVICE（默认 postgres）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 在 git worktree 里 ../ai-video 要相对主检出而不是相对 worktree：先定位主检出的根目录。
COMMON_DIR="$(git -C "$ROOT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
MAIN_ROOT="${COMMON_DIR:+$(dirname "$COMMON_DIR")}"
COMPOSE_FILE="${LEGACY_COMPOSE_FILE:-${MAIN_ROOT:-$ROOT_DIR}/../ai-video/docker-compose.yml}"
SERVICE="${LEGACY_PG_SERVICE:-postgres}"
OUT="${1:-$ROOT_DIR/data/legacy-export/styles.json}"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "找不到旧项目的 compose 文件：$COMPOSE_FILE（可用 LEGACY_COMPOSE_FILE 指定）" >&2
  exit 1
fi

PG_DB="$(awk '/POSTGRES_DB:/ {print $2; exit}' "$COMPOSE_FILE")"
PG_USER="$(awk '/POSTGRES_USER:/ {print $2; exit}' "$COMPOSE_FILE")"
if [ -z "$PG_DB" ] || [ -z "$PG_USER" ]; then
  echo "在 $COMPOSE_FILE 里没找到 POSTGRES_DB / POSTGRES_USER" >&2
  exit 1
fi

SQL="select json_build_object(
  'source', 'ai-video dev DB',
  'templates', (select coalesce(json_agg(json_build_object(
      'id', id, 'name', name, 'description', description, 'style_config', style_config
    ) order by name), '[]'::json) from style_templates),
  'components', (select coalesce(json_agg(json_build_object(
      'id', id, 'category', category, 'name', name, 'description', description,
      'prompt_text', prompt_text, 'is_builtin', is_builtin
    ) order by category, name), '[]'::json) from prompt_components)
);"

mkdir -p "$(dirname "$OUT")"
TMP="$OUT.tmp"
docker compose -f "$COMPOSE_FILE" exec -T -e PGOPTIONS="-c default_transaction_read_only=on" \
  "$SERVICE" psql -U "$PG_USER" -d "$PG_DB" -At -c "$SQL" > "$TMP"

# 先确认是合法 JSON 且两个数组都在，再替换目标文件。
python3 - "$TMP" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
templates, components = data["templates"], data["components"]
print(f"导出成功：{len(templates)} 个模板、{len(components)} 个组件")
PY
mv "$TMP" "$OUT"
echo "已写入 $OUT"
