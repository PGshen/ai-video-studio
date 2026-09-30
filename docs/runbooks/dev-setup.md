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

`.claude/launch.json`（Claude 桌面版 `preview_start` 用）不写本机绝对路径：`runtimeExecutable` 直接是 `uv`、`pnpm`，要求启动 Claude 桌面版的环境 `PATH` 里能找到这两个命令（例如 `~/.local/bin` 与 nvm 的 `bin` 目录已加入登录 shell 的 `PATH`）；找不到时改用 `make dev`。数据目录不在 launch.json 里指定，用默认的 `<仓库或 worktree 根>/data/`（`config.py` 按源码位置推算）；它只开 Fake 运行时（`STUDIO_ENABLE_FAKE_RUNTIME=true`），不导出 `backend/.env`，真实模型的 key 和 `TAVILY_API_KEY` 读不到（此时选题/头脑风暴的 `web_search` 会返回「TAVILY_API_KEY 未设置」）；要用真实模型和联网，用 `make dev`，或者先 `set -a; . backend/.env; set +a` 再手动起 uvicorn。

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

## 联网搜索（选题阶段、头脑风暴）

- 默认（`STUDIO_WEB_MODE=tools`）用自建的 `web_search`/`fetch_url`，后端是 Tavily：在 `backend/.env` 里填 `TAVILY_API_KEY`（裸环境变量，不带 `STUDIO_` 前缀，同 `VOLCENGINE_TTS_API_KEY`；`make dev`/`make smoke` 会导出）。免费额度够单人使用。没有 key 时这两个工具返回可读的错误，不会让一轮失败。
- `STUDIO_WEB_MODE=native`：改用运行时原生联网（Claude `WebSearch`/`WebFetch`；OpenAI 托管搜索），不需要 Tavily key，但没有「URL 来源」限制，提示注入外泄的风险回到 M1x 关闭联网前的状态，见 `docs/decisions/0010-联网模式开关.md`。OpenAI 路径经 OpenRouter 时托管搜索是否可用未验证。
- 两种模式互斥；narrative 和 animation 阶段在任何模式下都没有联网能力。
- 联网模式也可以在设置页（设置 → 通用）里切换，界面设置**覆盖**环境变量、下一轮对话起生效；「清除界面设置」回到环境变量的值（M5）。

## 设置页、风格库与语音（M5）

- **设置页**（`/settings`）：模型配置（增改删、单价、每轮预算；API key 的值仍然只放 `backend/.env`，界面只填环境变量的**名字**；由 `STUDIO_*` 网关变量决定的字段界面里只读）、风格库、语音、通用（各阶段默认模型、联网模式）。
- **旧项目的风格库**（一次性）：先在旧项目目录 `docker compose up -d postgres`，再在本仓库

  ```bash
  make export-legacy-styles   # 只读导出到 data/legacy-export/styles.json（不改旧项目任何文件）
  make import-legacy-styles   # 导入风格库；同名预设默认跳过，IMPORT_ARGS=--overwrite 才覆盖
  ```

  在 worktree 里开发时，`data/` 是 worktree 自己的目录，导入的风格不会出现在主检出的数据库里；合并后在主检出再跑一次（导出 JSON 复制过去，或重新导出）。
- **语音试听**会真实调用火山引擎 TTS（可能产生少量费用，同一音色+语速只合成一次、之后走 `data/tts-preview/` 缓存）：需要 `backend/.env` 里的 `VOLCENGINE_TTS_API_KEY`（裸环境变量，`make dev`/`make smoke` 会导出；手动起 uvicorn 要先 `set -a; . backend/.env; set +a`，否则试听返回 503 并提示去配置）。

## 模型网关（可选）

模型配置（`model_profiles`）的 `base_url`/`model` 可以由 `backend/.env` 里的三个可选项决定，启动时由种子写入（`seed_model_profiles`，F2）：

| 变量 | 作用于 | 例子 |
|---|---|---|
| `STUDIO_ANTHROPIC_BASE_URL` | `claude-sonnet`（API key 模式）的 `base_url`，ClaudeRuntime 把它作为 `ANTHROPIC_BASE_URL` 传给 CLI；`claude-login` 不受影响 | `https://ccproxy.yukework.com` |
| `STUDIO_OPENAI_BASE_URL` | `gpt` 的 `base_url`（`AsyncOpenAI(base_url=...)`） | `https://openrouter.ai/api/v1` |
| `STUDIO_OPENAI_MODEL` | `gpt` 的模型名；不设则为 `gpt-5` | `openai/gpt-5`（OpenRouter 的模型 id 带厂商前缀） |
| `STUDIO_OPENAI_PRICE_INPUT` | `gpt` 的输入单价，USD/百万 token；不设则用种子默认值 $1.25（对应 `gpt-5`） | `0.10` |
| `STUDIO_OPENAI_PRICE_OUTPUT` | `gpt` 的输出单价，USD/百万 token；不设则用种子默认值 $10 | `0.50` |

- key 仍然是 `ANTHROPIC_API_KEY`（填网关接受的 key）和 `OPENAI_API_KEY`（走 OpenRouter 时填 OpenRouter key）。
- 种子规则：配置值非空时，新库直接用它建行；**已有的库**在值不同时只更新对应字段（`base_url`/`model` 两个一组，`price_input`/`price_output` 两个一组，互不影响预算等其他字段）。配置值为空（或删掉这一行）时不会把已有值清空——要回到官方地址/默认单价，需要把对应变量手动改回空或删库重建。
- `gpt` 走非 `api.openai.com` 的地址（例如 OpenRouter）时，OpenAI 运行时**不提供 Shell**（OpenRouter 的 `shell` 只在托管沙箱里执行，看不到本地工作区），改给只读的 `list_files`/`read_file`，写文件仍用原生 `apply_patch`；联网搜索仍是 `web_search`。依据见 `docs/references/openai-agents-sdk.md`。
- 单价：OpenRouter 上 `openai/gpt-5` 与 OpenAI 官方同价（$1.25/$10 每百万 token），种子单价不变。换成单价不同的型号（例如 OpenRouter 上单价更低的替代型号）时用 `STUDIO_OPENAI_PRICE_INPUT`/`STUDIO_OPENAI_PRICE_OUTPUT` 覆盖，否则成本统计会用 `gpt-5` 的单价偏高估算（G2，2026-09-28）。
- `gpt-5-2025-08-07`（OpenRouter 经 Azure/OpenAI 后端）不支持 `apply_patch` 工具，调用会返回 400 `Tool 'apply_patch' is not supported with gpt-5-2025-08-07.`（`make smoke` 第 2 次运行实测，2026-09-28，见 `docs/references/openai-agents-sdk.md`）；换用支持 `apply_patch` 的型号时记得同时按上面两行设置单价。

### 已知限制

- `deepseek` 种子的 `supports_vision` 已改为 `False`（`deepseek/deepseek-flash` 不支持图片输入，2026-09-28 冒烟实测，见 `docs/references/openai-agents-sdk.md` R2）。`seed_model_profiles` 只在建新行时使用种子默认值，**已有数据库**里若在这次改动之前已插入过 `deepseek` 行（`supports_vision=True`），本次改动不会自动更新它——需要手动执行 `sqlite3 <data_dir>/studio.db "UPDATE model_profiles SET supports_vision = 0 WHERE name = 'deepseek';"`，或者直接删掉整个 `data/`（或 `STUDIO_DATA_DIR` 指向的目录）重建。

## 启动

```bash
make dev
```

会执行 `scripts/dev.sh`：同时启动后端（`uvicorn studio.main:app --reload --reload-dir <绝对路径>/backend/src`）和前端（`cd frontend && pnpm run dev`），两者共用一个 trap，`Ctrl+C` 会一起结束。

启动后可以访问：
- 后端：http://127.0.0.1:8000（健康检查 `/api/health`，OpenAPI 文档在 `/docs`）
- 前端：http://127.0.0.1:5173（`vite.config.ts` 绑定 `127.0.0.1:5173`、`strictPort: true`，并把 `/api` 代理到 `http://127.0.0.1:8000`，SSE 接口也经代理透传，不缓冲）
