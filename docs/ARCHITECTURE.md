# ARCHITECTURE：模块地图与分层规则

完整设计见 [design/2026-09-26-architecture.md](design/2026-09-26-architecture.md)。本文件只描述**代码结构**和**依赖方向**，内容必须和代码保持一致（SOP §10）。
下面的分层规则会写成 import-linter 契约，由 `make check` 强制检查（M1 接入）。

> 状态：M1 开始前，描述的是目标结构。每个里程碑收尾时按实际代码更新。

## 1. 仓库顶层

```
ai-video-studio/
  AGENTS.md / CLAUDE.md   # AI 入口
  Makefile                # 命令入口；make check 是唯一的质量关口
  backend/                # Python 3.12 + FastAPI，uv 管理
  frontend/               # Vue 3 + Vite + TS + Tailwind v4 + shadcn-vue
  data/                   # 运行时数据（不进 git）
  docs/                   # 知识库
  scripts/                # 开发脚本（文档检查等）
  .githooks/              # pre-commit
```

## 2. 后端模块（`backend/src/studio/`）

| 模块 | 职责 | 可以依赖 |
|---|---|---|
| `config` | 配置：数据目录、模型 key、搜索 key | — |
| `db` | SQLite 连接（WAL）、ORM 模型、迁移 | `config` |
| `engines.render` | manim 渲染：预览、成片、关键帧抽取 | `config` |
| `engines.tts` | 语音合成、beat 对齐 | `config` |
| `search` | 搜索提供方接口，以及 Tavily 实现 | `config` |
| `workspace` | 工作区布局、快照库、diff、回滚、越界检查、上游只读副本 | `db`、`config` |
| `jobs` | SQLite 任务队列：领取、心跳、结果 | `db`、`config` |
| `agent` | 运行时抽象、Claude/OpenAI/Fake 适配器、`ToolSpec`、会话总线、TurnRunner | `workspace`、`db`、`config` |
| `stages.common` | 各阶段共用：阶段定义协议、`suggest_upstream_change` 等通用工具 | `agent`、`workspace`、`db`、`config` |
| `stages.<brainstorm\|topic\|narrative\|animation>` | 各阶段的提示词、专属工具、产物 schema、校验器、定稿逻辑 | `stages.common`、`agent`、`workspace`、`engines`、`search`、`jobs`、`db`、`config` |
| `api` | HTTP 路由、SSE | 以上全部 |
| `main` | api 进程入口：组装应用，**注册各阶段** | 以上全部 |
| `worker` | worker 进程入口：成片任务循环 | `jobs`、`engines`、`workspace`、`db`、`config` |

### 分层规则（机器检查）

1. **没有模块 import `api`、`main`、`worker`**：它们是组装层。
2. **`agent` 不 import `stages`**：TurnRunner 只认识"阶段定义协议"（提示词、工具列表、可写路径、上下文前言构建器），具体阶段在 `main` 中注册。这样运行时层和业务逻辑解耦。
3. **各阶段之间互不 import**：`stages.narrative` 不能 import `stages.animation`，共用代码放进 `stages.common`。
4. **`engines`、`search` 是纯能力层**：只依赖 `config`，不访问数据库，不知道项目和阶段的存在，方便单独测试和复用。
5. **只有 `db` 定义 ORM 模型**；其他模块通过 `db` 提供的仓储函数读写数据。
6. **`workspace` 是唯一读写工作区文件的模块**；agent 的原生文件工具除外，它们受越界检查约束。

## 3. 前端模块（`frontend/src/`）

| 目录 | 职责 |
|---|---|
| `pages/` | 路由页面（组合层）：`router.ts` 指向这里；可以 import 多个 `features/`，把它们拼成一个页面 |
| `api/` | 类型化的 HTTP 客户端和 SSE 客户端（支持 `after_seq` 续传） |
| `types/` | 与后端 schema 对应的 TS 类型 |
| `composables/` | TanStack Query hooks 和会话流状态 |
| `features/projects/` | 项目列表、新建项目 |
| `features/ideas/` | 选题池和头脑风暴 |
| `features/workbench/` | 项目工作台外壳：阶段导航、对话面板、快照时间线 |
| `features/canvas/<topic\|narrative\|animation>/` | 各阶段的画布 |
| `features/settings/` | 模型配置、风格库、TTS 音色 |
| `components/ui/` | shadcn-vue 生成的组件（通过 CLI 添加，尽量不手改） |
| `components/ai-elements/` | @ai-elements 生成的组件（通过 CLI 添加，尽量不手改） |

规则：`features/*` 之间不互相 import，共用的内容放进 `components/` 或 `composables/`。`components/` 不 import `features/` 或 `pages/`。`pages/` 可以 import `features/`（组合层）。由 `frontend/eslint.config.ts` 中的 `no-restricted-imports` 规则检查（T11 接入；未用 `eslint-plugin-boundaries`，格式规则对 `components/ui`、`components/ai-elements` 下的生成代码放宽）。

## 4. 进程与数据流

```
浏览器 ──HTTP/SSE──▶ api 进程（FastAPI + agent 会话 + 预览渲染）
                        │   ▲
                SQLite  │   │  jobs 进度轮询
                        ▼   │
                     worker 进程（成片渲染）
两个进程共用：data/studio.db、data/blobs/、data/projects/<id>/
```
