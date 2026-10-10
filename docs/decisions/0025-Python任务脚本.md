# 0025：Python 任务脚本是工具链的唯一逻辑来源

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳 |
| 日期 | 2026-10-09 |
| 相关 | [windows-native-support 设计](../design/2026-10-09-windows-native-support.md) §7、§8；[windows-native 计划](../plans/active/windows-native.md) T1、T7；[ADR 0006](0006-纯本地SOP.md) |

## 背景

质量关口、依赖安装、冒烟测试和开发进程原来都写在 Makefile 和 bash 脚本里（`SHELL := /bin/bash`、`set -a; . backend/.env`、`env -i`、`compgen`、进程组）。Windows 原生环境没有这些：负责人要在 Windows 11 上既能使用也能开发（运行 `make check` 的等价物、提交时跑 pre-commit），继续维护两套脚本又会让两边的行为慢慢分叉。

## 决定

- `scripts/tasks.py` 是工具链逻辑的**唯一来源**：单个文件，只用标准库，不 import `studio`（`backend/.venv` 不完整时也要能跑）。子命令和原来的 Makefile 目标一一对应：`setup`、`check`、`check-fast`、`check-docs`、`check-backend`、`check-frontend`、`smoke`、`import-legacy-styles`，以及（计划 T7 之后）`dev`。
- 统一的调用方式是在仓库根目录运行 `uv run --project backend python scripts/tasks.py <子命令>`。Windows（PowerShell）上直接用这条命令；macOS 上 `make <目标>` 保持不变，Makefile 每个目标只有一行，转调 `tasks.py` 的同名子命令。`make check` 仍然是质量关口的名字，Windows 上的等价写法是 `tasks.py check`。
- Makefile 里只保留定位 `uv` 的逻辑，因为它是调用 `tasks.py` 的前提；`uv`、`pnpm` 的其他定位逻辑搬进 `tasks.py`（先 `shutil.which`，再看各平台的常见安装位置）。
- `backend/.env` 由 `tasks.py` 自己按 shell 语法的字面量子集解析（`KEY=VALUE`、`export` 前缀、单双引号、`#` 注释），遇到变量展开、命令替换、反斜杠转义时报错并指出行号，绝不静默错读。
- `smoke` 用 Python 实现原来 `env -i` + 白名单的效果，两个平台各有一份运行必需变量的白名单（设计 §8.3）。
- pre-commit hook 调用 `tasks.py check-fast`，hook 文件本身仍是 sh 脚本（Git for Windows 用自带的 sh 执行）。
- 仓库加 `.gitattributes`：`* text=auto eol=lf`，二进制资产标 `binary`；行尾不再依赖各机器的 `core.autocrlf`。
- **不迁移** `export-legacy-styles`（只读导出旧项目的风格库，依赖旧项目的 postgres 容器，一次性的、只在 macOS 上用过）和 `build_fonts.sh`，它们保持 bash 版。

## 考虑过的其他方案

- **Makefile + bash 保留，Windows 上要求 Git Bash/MSYS 的 make**：不选的原因：`env -i`、进程组、`lsof` 在 Git Bash 下行为不一致；Claude Code 在 Windows 上默认用 PowerShell，开发会话里也不方便。
- **Makefile 和一份 PowerShell 脚本并存**：不选的原因：两套逻辑会分叉，测试只能覆盖其中一套。
- **引入 nox/invoke/just 等任务工具**：不选的原因：设计 §2 不引入新依赖；需求只是十来个子命令，标准库足够。

## 影响

- 工具链的行为有了单元测试（`backend/tests/scripts/test_tasks.py`）：`.env` 解析、冒烟白名单、可执行文件的查找、Makefile 是否只是薄壳。
- 新增或修改命令时，改 `tasks.py`，Makefile 只加一行转调；`tests/scripts/test_tasks.py::test_makefile_targets_are_thin_wrappers` 会检查两边对得上。
- `tasks.py` 不在 `backend` 的 ruff/pyright 范围内，它的 lint 由计划 T2 另行接入。
