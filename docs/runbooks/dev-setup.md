# 开发环境搭建

> 本文件描述的是目标环境。T1 已校对后端部分；前端部分在 T11 落地后再校对。

## 前置依赖（macOS）

| 依赖 | 用途 | 安装 |
|---|---|---|
| uv | Python 包管理，Python 3.12 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node 22+ 和 pnpm | 前端 | nvm 或 brew；`corepack enable` |
| cairo、pango、pkg-config | manim 的原生依赖 | `brew install cairo pango pkg-config` |
| ffmpeg | 渲染、音频合成、关键帧抽取 | `brew install ffmpeg` |
| LaTeX | manim 的公式渲染 | `brew install --cask mactex-no-gui`（或 BasicTeX 加所需的宏包） |

## 命令行路径

Claude Code 沙箱中的 `PATH` 可能不包含 `~/.local/bin` 和 nvm 的 shims。Makefile 自己定位 `uv` 和 `pnpm`（`UV`/`PNPM` 变量，见 `Makefile` 开头），不依赖调用方的 `PATH`。在 Makefile 之外手动执行时，使用绝对路径，例如 `~/.local/bin/uv run pytest`（在 `backend/` 目录下）。

## 初始化

```bash
make setup
```

这一步会安装后端（`cd backend && uv sync`）和前端（`frontend/` 出现后自动生效）的依赖，并执行 `git config core.hooksPath .githooks`，启用 pre-commit（跑 `make check-fast`）。

`uv sync` 会在需要时自动下载锁定的 Python 3.12（`backend/pyproject.toml` 里 `requires-python = ">=3.12,<3.13"`），不需要手动安装。

## 配置

- 后端配置从 `backend/.env` 读取（`STUDIO_` 前缀的环境变量），参考 `backend/.env.example`：数据目录、host/port、并发数、是否启用 Fake 运行时。模型 key（如 `ANTHROPIC_API_KEY`）不是 `Settings` 字段，由模型配置的 `api_key_env` 按名读取，也写在 `backend/.env` 里。
- 数据目录（`data_dir`）默认为仓库根目录下的 `data/`，可以用 `STUDIO_DATA_DIR` 指向其他位置；解析后的路径不能落在 `backend/src` 之下（否则启动时报错），因为那会被 uvicorn `--reload` 监听到。

## 启动

```bash
make dev
```

会执行 `scripts/dev.sh`：目前只启动后端（`uvicorn studio.main:app --reload --reload-dir <绝对路径>/backend/src`），前端在 T11 加入后同时启动。

启动后可以访问：
- 后端：http://127.0.0.1:8000（健康检查 `/api/health`，OpenAPI 文档在 `/docs`）
- 前端（T11 起）：http://127.0.0.1:5173
