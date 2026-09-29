# make check 是唯一的质量关口（docs/SOP.md）。
# 后端和前端的检查会在对应目录出现后自动生效；M1 负责把具体命令接进来。

SHELL := /bin/bash

# Claude Code 沙箱的 PATH 可能不包含 ~/.local/bin 和 nvm shims，这里主动定位。
UV   ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
PNPM ?= $(shell command -v pnpm 2>/dev/null || ls -d $(HOME)/.nvm/versions/node/*/bin/pnpm 2>/dev/null | tail -1)
PYTHON ?= python3

HAS_BACKEND  := $(wildcard backend/pyproject.toml)
HAS_FRONTEND := $(wildcard frontend/package.json)

.PHONY: setup check check-fast check-docs check-backend check-frontend dev smoke

setup:
	git config core.hooksPath .githooks
ifneq ($(HAS_BACKEND),)
	cd backend && $(UV) sync
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && $(PNPM) install
endif

check: check-docs check-backend check-frontend
	@echo "make check 全部通过"

# pre-commit 运行的快速子集。
check-fast: check-docs
ifneq ($(HAS_BACKEND),)
	cd backend && $(UV) run ruff check .
endif
ifneq ($(HAS_FRONTEND),)
	cd frontend && $(PNPM) run lint
endif

check-docs:
	@$(PYTHON) scripts/check_docs.py

check-backend:
ifneq ($(HAS_BACKEND),)
	cd backend && $(UV) run ruff check .
	cd backend && $(UV) run ruff format --check .
	cd backend && $(UV) run pyright
	cd backend && $(UV) run lint-imports
	cd backend && $(UV) run pytest
else
	@echo "跳过后端检查：backend/ 尚未创建"
endif

check-frontend:
ifneq ($(HAS_FRONTEND),)
	cd frontend && $(PNPM) run lint
	cd frontend && $(PNPM) run typecheck
	cd frontend && $(PNPM) exec vitest run
else
	@echo "跳过前端检查：frontend/ 尚未创建"
endif

dev:
	@bash scripts/dev.sh

# 真实模型的冒烟测试（计划 T15）：先导出 backend/.env（同 scripts/dev.sh），再用 env -i
# 只带白名单变量运行 pytest——在 Claude Code 等宿主里执行时，宿主注入的 CLAUDE_CODE_* /
# ANTHROPIC_BASE_URL 等变量不会带进用例。缺 key 的用例自动跳过。默认 make check 不含它。
SMOKE_KEYS := ANTHROPIC_API_KEY OPENAI_API_KEY DEEPSEEK_API_KEY VOLCENGINE_TTS_API_KEY

smoke:
	@set -a; [ -f backend/.env ] && . backend/.env; set +a; \
	args=(HOME="$$HOME" PATH="$$PATH" USER="$$USER" LANG="$${LANG:-en_US.UTF-8}" \
	      TMPDIR="$${TMPDIR:-/tmp}" SHELL="$${SHELL:-/bin/bash}"); \
	for v in $(SMOKE_KEYS) $$(compgen -e | grep '^STUDIO_'); do \
	  [ -n "$${!v:-}" ] && args+=("$$v=$${!v}"); \
	done; \
	echo "make smoke: env -i + 白名单变量（$${#args[@]} 个）"; \
	cd backend && env -i "$${args[@]}" $(UV) run pytest -m smoke -v -rs $(SMOKE_ARGS)
