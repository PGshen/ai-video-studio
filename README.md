# ai-video-studio

单人本地使用的对话式 AI 知识视频工作台：选题打磨 → 叙事 → 动画（代码 + 成片），每个阶段都通过和 agent 对话来打磨产物。

agent 直接修改工作区文件，每轮结束自动打快照，可以随时回滚；下游阶段发现上游有问题时，可以提出回退建议，由你决定是否处理。

## 当前状态

M1–M5 已完成，主流程可用：

| 能力 | 说明 |
|---|---|
| 头脑风暴与选题池 | 没有项目的对话，agent 联网搜索并往选题池写想法卡片；从卡片创建项目 |
| 三个阶段 | `topic`（选题简报）→ `narrative`（叙事 JSON）→ `animation`（manim 场景代码、配音、预览与成片渲染） |
| 画布式对话 | 左侧对话、右侧产物画布；每轮自动快照，可查看差异和回滚；阶段可定稿，上游变更后下游标记为 stale |
| 回退建议 | 下游 agent 向直接上游提修改建议，在对话流里显示为卡片，阶段导航上有待处理角标，可「去处理」或忽略 |
| 风格库 | 风格是 skill 形态的目录（`STYLE.md` + `references/` + `exemplars/`），创建项目时选一套，各阶段 agent 按需读取；支持从旧项目一次性导入 |
| 设置页 | 模型配置增改删（单价、每轮预算）、各阶段默认模型、联网模式、语音音色与语速（可试听） |
| 会话内换模型 | 对话中可换成同运行时、同供应商的其他模型，下一轮起生效 |
| 双运行时 | 同时支持 Claude Agent SDK 和 OpenAI Agents SDK；Claude 可以直接用本机 `claude` 登录，不需要 API key |

## 快速开始

前置依赖（macOS）：uv、Node 22+ 与 pnpm、cairo/pango/pkg-config、ffmpeg、LaTeX。完整说明见 [环境搭建](docs/runbooks/dev-setup.md)。

```bash
make setup          # 安装依赖，启用 git hooks
cp backend/.env.example backend/.env   # 然后按需填模型 key
make dev            # 同时启动 api、worker、frontend
```

- 前端：http://127.0.0.1:5173
- 后端：http://127.0.0.1:8000（健康检查 `/api/health`，OpenAPI 在 `/docs`）

`backend/.env` 里的常用项（详见 [环境搭建](docs/runbooks/dev-setup.md)）：

- 模型 key：`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 等，按模型配置的 `api_key_env` 读取；key 的值只放在这里，设置页只填环境变量的名字。
- 联网搜索：`TAVILY_API_KEY`（默认 `STUDIO_WEB_MODE=tools`）；也可在设置页切换联网模式。
- 语音：`VOLCENGINE_TTS_API_KEY`（配音与设置页试听；试听会产生少量真实费用，同一音色和语速只合成一次并缓存）。
- 模型网关（可选）：`STUDIO_ANTHROPIC_BASE_URL`、`STUDIO_OPENAI_BASE_URL`、`STUDIO_OPENAI_MODEL` 等。

### 导入旧项目的风格库（一次性，可选）

先在旧项目目录 `docker compose up -d postgres`，再在本仓库执行：

```bash
make export-legacy-styles   # 只读导出到 data/legacy-export/styles.json，不改旧项目任何文件
make import-legacy-styles   # 同名预设默认跳过，IMPORT_ARGS=--overwrite 才覆盖
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `make setup` | 安装依赖，启用 git hooks |
| `make dev` | 启动 api、worker、frontend 三个进程 |
| `make check` | 唯一的质量关口：lint、类型检查、测试、结构测试、文档检查 |
| `make check-fast` | pre-commit 运行的快速子集 |
| `make smoke` | 需要真实 API key 的冒烟测试（默认不包含在 `make check` 中，会产生费用） |

## 仓库结构

```
backend/     Python 3.12 + FastAPI + SQLite，uv 管理；api 与 worker 两个进程
frontend/    Vue 3 + Vite + TypeScript + Tailwind v4 + shadcn-vue
data/        运行时数据：数据库、各项目工作区与快照（不进 git，也不放在 uvicorn reload 监听范围内）
docs/        知识库：设计、计划、决策、参考、质量
scripts/     开发脚本
```

## 文档

- 设计：[docs/design/2026-09-26-architecture.md](docs/design/2026-09-26-architecture.md)
- 模块地图与分层规则：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 开发流程：[docs/SOP.md](docs/SOP.md)
- 术语表：[docs/glossary.md](docs/glossary.md)
- 决策记录（ADR）：[docs/decisions/](docs/decisions/)
- 模块质量与已知缺口：[docs/quality/QUALITY.md](docs/quality/QUALITY.md)；技术债：[docs/quality/tech-debt.md](docs/quality/tech-debt.md)
- 环境搭建与验证方法：[docs/runbooks/dev-setup.md](docs/runbooks/dev-setup.md)、[docs/runbooks/verification.md](docs/runbooks/verification.md)
- AI 开发者入口：[AGENTS.md](AGENTS.md)
