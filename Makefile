# make check 是唯一的质量关口（docs/SOP.md）。
# 所有逻辑都在 scripts/tasks.py（ADR 0025）；这里每个目标只是一行转调，macOS 上用法不变。
# Windows 上不用 make，直接运行：uv run --project backend python scripts/tasks.py <目标>

# Claude Code 沙箱的 PATH 可能不包含 ~/.local/bin，这里主动定位（调用 tasks.py 的前提）。
UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
TASKS := $(UV) run --project backend python scripts/tasks.py

.PHONY: setup check check-fast check-docs check-backend check-frontend dev smoke \
        export-legacy-styles import-legacy-styles

setup:
	@$(TASKS) setup

check:
	@$(TASKS) check

# pre-commit 运行的快速子集。
check-fast:
	@$(TASKS) check-fast

check-docs:
	@$(TASKS) check-docs

check-backend:
	@$(TASKS) check-backend

check-frontend:
	@$(TASKS) check-frontend

dev:
	@bash scripts/dev.sh

# 真实模型的冒烟测试：只带白名单变量运行 pytest -m smoke（见 tasks.py smoke_env）。
smoke:
	@$(TASKS) smoke $(SMOKE_ARGS)

# 旧项目风格库的一次性迁移（计划 M5 T4）：先只读导出成 JSON（需要旧项目的 postgres 容器在
# 运行，只有 bash 版，ADR 0025），再导入新风格库。同名预设默认跳过，IMPORT_ARGS=--overwrite 才覆盖。
LEGACY_STYLES_FILE ?= data/legacy-export/styles.json

export-legacy-styles:
	@bash scripts/export_legacy_styles.sh $(LEGACY_STYLES_FILE)

import-legacy-styles:
	@$(TASKS) import-legacy-styles $(abspath $(LEGACY_STYLES_FILE)) $(IMPORT_ARGS)
