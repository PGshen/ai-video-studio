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

smoke:
	@echo "TODO(M1): 运行需要真实 key 的冒烟测试" && exit 1
