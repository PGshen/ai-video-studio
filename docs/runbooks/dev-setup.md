# 开发环境搭建

> 本文件描述的是目标环境。T1 已校对后端部分；T11 已校对前端部分。

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

`.claude/launch.json`（Claude 桌面版 `preview_start` 用）不写本机绝对路径：`runtimeExecutable` 直接是 `uv`、`pnpm`，要求启动 Claude 桌面版的环境 `PATH` 里能找到这两个命令（例如 `~/.local/bin` 与 nvm 的 `bin` 目录已加入登录 shell 的 `PATH`）；找不到时改用 `make dev`。数据目录不在 launch.json 里指定，用默认的 `<仓库或 worktree 根>/data/`（`config.py` 按源码位置推算）；它只开 Fake 运行时（`STUDIO_ENABLE_FAKE_RUNTIME=true`），不导出 `backend/.env`，真实模型的 key 读不到。

Fake 运行时可以用 `STUDIO_FAKE_DELAY_SECONDS=<秒>` 让默认脚本在回显和写文件之间停一会儿（可被取消），便于观察"运行中"状态、做重启中断验证；默认 0。

## 初始化

```bash
make setup
```

这一步会安装后端（`cd backend && uv sync`）和前端（`frontend/` 出现后自动生效）的依赖，并执行 `git config core.hooksPath .githooks`，启用 pre-commit（跑 `make check-fast`）。

`uv sync` 会在需要时自动下载锁定的 Python 3.12（`backend/pyproject.toml` 里 `requires-python = ">=3.12,<3.13"`），不需要手动安装。

## 配置

- 后端配置从 `backend/.env` 读取（`STUDIO_` 前缀的环境变量），参考 `backend/.env.example`：数据目录、host/port、并发数、是否启用 Fake 运行时。模型 key（如 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`）不是 `Settings` 字段，运行时按模型配置的 `api_key_env` 从**进程环境变量**读取；也写在 `backend/.env` 里——`scripts/dev.sh`（`make dev`）启动前会用 `set -a; . backend/.env; set +a` 把它整体导出到环境中（`make smoke` 在 T15 同样处理）。直接手动运行 `uvicorn` 时要自己导出，否则 key 读不到，对应模型的 turn 会以"环境变量未设置"失败。`backend/.env` 按 shell 语法解析（值里有空格或特殊字符要加引号）。
- 数据目录（`data_dir`）默认为仓库根目录下的 `data/`，可以用 `STUDIO_DATA_DIR` 指向其他位置；解析后的路径不能落在 `backend/src` 之下（否则启动时报错），因为那会被 uvicorn `--reload` 监听到。

## 模型网关（可选）

模型配置（`model_profiles`）的 `base_url`/`model` 可以由 `backend/.env` 里的三个可选项决定，启动时由种子写入（`seed_model_profiles`，F2）：

| 变量 | 作用于 | 例子 |
|---|---|---|
| `STUDIO_ANTHROPIC_BASE_URL` | `claude-sonnet`（API key 模式）的 `base_url`，ClaudeRuntime 把它作为 `ANTHROPIC_BASE_URL` 传给 CLI；`claude-login` 不受影响 | `https://ccproxy.yukework.com` |
| `STUDIO_OPENAI_BASE_URL` | `gpt` 的 `base_url`（`AsyncOpenAI(base_url=...)`） | `https://openrouter.ai/api/v1` |
| `STUDIO_OPENAI_MODEL` | `gpt` 的模型名；不设则为 `gpt-5` | `openai/gpt-5`（OpenRouter 的模型 id 带厂商前缀） |

- key 仍然是 `ANTHROPIC_API_KEY`（填网关接受的 key）和 `OPENAI_API_KEY`（走 OpenRouter 时填 OpenRouter key）。
- 种子规则：配置值非空时，新库直接用它建行；**已有的库**在值不同时只更新这两个字段（其他字段、单价、预算不动）。配置值为空（或删掉这一行）时不会把已有值清空——要回到官方地址，需要把 `base_url` 手动改回空或删库重建。
- `gpt` 走非 `api.openai.com` 的地址（例如 OpenRouter）时，OpenAI 运行时**不提供 Shell**（OpenRouter 的 `shell` 只在托管沙箱里执行，看不到本地工作区），改给只读的 `list_files`/`read_file`，写文件仍用原生 `apply_patch`；联网搜索仍是 `web_search`。依据见 `docs/references/openai-agents-sdk.md`。
- 单价：OpenRouter 上 `openai/gpt-5` 与 OpenAI 官方同价（$1.25/$10 每百万 token），种子单价不变。

## 启动

```bash
make dev
```

会执行 `scripts/dev.sh`：同时启动后端（`uvicorn studio.main:app --reload --reload-dir <绝对路径>/backend/src`）和前端（`cd frontend && pnpm run dev`），两者共用一个 trap，`Ctrl+C` 会一起结束。

启动后可以访问：
- 后端：http://127.0.0.1:8000（健康检查 `/api/health`，OpenAPI 文档在 `/docs`）
- 前端：http://127.0.0.1:5173（`vite.config.ts` 绑定 `127.0.0.1:5173`、`strictPort: true`，并把 `/api` 代理到 `http://127.0.0.1:8000`，SSE 接口也经代理透传，不缓冲）
