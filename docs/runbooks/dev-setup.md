# 开发环境搭建

> 本文件描述的是目标环境。M1 搭好骨架后，执行者按实际安装步骤校对并更新。

## 前置依赖（macOS）

| 依赖 | 用途 | 安装 |
|---|---|---|
| uv | Python 包管理，Python 3.12 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node 22+ 和 pnpm | 前端 | nvm 或 brew；`corepack enable` |
| cairo、pango、pkg-config | manim 的原生依赖 | `brew install cairo pango pkg-config` |
| ffmpeg | 渲染、音频合成、关键帧抽取 | `brew install ffmpeg` |
| LaTeX | manim 的公式渲染 | `brew install --cask mactex-no-gui`（或 BasicTeX 加所需的宏包） |

## 命令行路径

Claude Code 沙箱中的 `PATH` 可能不包含 `~/.local/bin` 和 nvm 的 shims。Makefile 应该自己定位 `uv` 和 `pnpm`，不依赖调用方的 `PATH`（M1 实现）。在 Makefile 之外手动执行时，使用绝对路径，例如 `~/.local/bin/uv`。

## 初始化

```bash
make setup
```

这一步会安装后端和前端的依赖，并执行 `git config core.hooksPath .githooks`，启用 pre-commit。

## 配置

- 后端配置从 `backend/.env` 读取，参考 `backend/.env.example`：模型 key、Tavily key、数据目录。
- 数据目录默认为仓库下的 `data/`，也可以用 `STUDIO_DATA_DIR` 指向其他位置。

## 启动

```bash
make dev
```

启动后可以访问：
- 后端：http://127.0.0.1:8000（OpenAPI 文档在 `/docs`）
- 前端：http://127.0.0.1:5173
