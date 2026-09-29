# ARCHITECTURE：模块地图与分层规则

完整设计见 [design/2026-09-26-architecture.md](design/2026-09-26-architecture.md)。本文件只描述**代码结构**和**依赖方向**，内容必须和代码保持一致（SOP §10）。
下面的分层规则写成了 import-linter 契约（`backend/pyproject.toml` 的 `[tool.importlinter]`），由 `make check` 强制检查。

> 状态：M2 收尾时按实际代码更新（2026-09-29）。表中标注"（M3/M4/M5）"的模块还不存在，建立时按控制者裁定 R1 把对应契约补进 `pyproject.toml`。

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
| `engines.render` | manim 渲染：静态校验、全画质渲染（`manim/{script,process,engine}.py`）、预览与关键帧抽取（T2） | `config` |
| `engines.tts`（M3） | 语音合成、beat 对齐 | `config` |
| `search`（M4） | 搜索提供方接口，以及 Tavily 实现 | `config` |
| `workspace` | 工作区布局（`layout`）、快照库与 diff/回滚（`snapshot`、`blobs`）、越界检查（`scope`）、上游只读副本（`upstream`）、受控文件读写与建/删工作区（`files`） | `db`、`config` |
| `jobs` | SQLite 任务队列：`create_job`/`claim_next`/`heartbeat`/`update_progress`/`complete`/`fail`/`get_job`/`list_jobs`/`reap_stale_running`；`jobs.repo` 转发自 `db.repo.jobs`（`Job` 模型的直接读写按规则 5 留在 `db.repo`） | `db`、`config` |
| `agent` | 事件（`events`）、`ToolSpec`（`tools`）、运行时协议与注册表（`runtime`）、**阶段定义协议与注册表（`stage`）**、**阶段流转：定稿/重新打开/stale（`stage_flow`）**、会话总线（`bus`）、上下文前言（`preamble`）、TurnRunner（`runner`：公开接口、排队调度、`_persist`/`_publish` 等总线基础方法；一轮生命周期的其余部分拆到同包内的 `turn_state`——`_Job`/`_State` 共享结构、`turn_events`——运行时事件落库与推送、`turn_finish`——收尾（越界检查/快照/写状态）、`recovery`——重启恢复，见 TD-15）、Claude/OpenAI/Fake 适配器（`claude_runtime` 中环境变量拆到 `claude_env`，读写范围 hook 与 Bash sandbox 配置拆到 `claude_scope`，SDK 消息转换与业务工具桥接拆到 `claude_messages`；`openai_runtime` 中 `LocalShellExecutor` 拆到 `shell`（经 macOS `sandbox-exec` 执行，Seatbelt 配置生成与平台判断在 `shell_sandbox`），业务工具桥接与 item→事件转换拆到 `openai_tools`）、兜底文件工具与 `ApplyPatchEditor` | `workspace`、`db`、`config` |
| `stages.common` | 各阶段共用的业务工具：`suggest_upstream_change`（M2 T6 已实现，写 `suggestions` 表；因 `ToolContext` 拿不到 `Engine`，暂未接入 `AnimationStage.tools()`，见 TD-32） | `agent`、`workspace`、`db`、`config` |
| `stages.<topic\|narrative\|animation>`（brainstorm 在 M4） | 各阶段的提示词、专属工具、产物 schema、校验器，实现 `agent.stage.StageDefinition`；`animation`（M2）已有完整提示词 + `validate_scenes`/`render_preview` 工具，`topic`/`narrative` 仍是 M1 占位定义（提示词 + 可写范围） | `stages.common`、`agent`、`workspace`、`engines`、`search`、`jobs`、`db`、`config` |
| `api` | HTTP 路由、SSE | 以上全部（除 `main`） |
| `main` | api 进程入口：组装应用，**注册各阶段**与各运行时，lifespan 关闭时收尾运行中的 turn | 以上全部 |
| `worker` | worker 进程入口：成片任务循环（M2 T5） | `jobs`、`engines`、`workspace`、`db`、`config` |

### 分层规则（机器检查）

1. **没有模块 import `api`、`main`、`worker`**：它们是组装层。
2. **`agent` 不 import `stages`**：TurnRunner 只认识"阶段定义协议"（`agent/stage.py` 的 `StageDefinition`：提示词、工具列表、可写范围、上下游、状态摘要），具体阶段在 `main` 中注册进 `StageRegistry`。这样运行时层和业务逻辑解耦。阶段流转中与具体阶段无关的部分（定稿、重新打开、下游 stale）也在 `agent/stage_flow.py`。
3. **各阶段之间互不 import**：`stages.narrative` 不能 import `stages.animation`，共用代码放进 `stages.common`。
4. **`engines`、`search` 是纯能力层**：只依赖 `config`，不访问数据库，不知道项目和阶段的存在，方便单独测试和复用。
5. **只有 `db` 定义 ORM 模型**；其他模块通过 `db` 提供的仓储函数读写数据。
6. **`workspace` 是唯一读写工作区文件的模块**；agent 的原生文件工具除外，它们受越界检查约束。

规则 1–5 的机器检查：一条 `layers` 契约（`main > api > stages > agent > workspace > db > config`，下层不能 import 上层，含间接 import）覆盖依赖表；`agent` 不 import `stages`（规则 2）另有单独契约；三个阶段之间是 `independence` 契约（规则 3）；`workspace`/`agent`/`stages`/`api`/`main` 各有一条"不直接 import `db.models`"的契约（规则 5）。规则 4：`engines` 已有一条"只依赖 `config`"的 `forbidden` 契约（M2 T1）；`search`（M4）待模块建立时补。规则 6 靠代码评审：api 通过 `workspace.files`（`write_text`、`init_workspace`、`remove_workspace` 等）和 `workspace.snapshot` 操作工作区。

## 3. 前端模块（`frontend/src/`）

| 目录 | 职责 |
|---|---|
| `pages/` | 路由页面（组合层）：`router.ts` 指向这里；可以 import 多个 `features/`，把它们拼成一个页面（`ProjectsPage`、`ProjectWorkbenchPage`、占位的 `IdeasPage`/`SettingsPage`） |
| `api/` | 类型化的 HTTP 客户端和 SSE 客户端（支持 `after_seq` 续传） |
| `types/` | 与后端 schema 对应的 TS 类型 |
| `composables/` | TanStack Query hooks 和会话流状态 |
| `features/projects/` | 项目列表、新建项目（`ProjectList.vue`） |
| `features/ideas/`（M4） | 选题池和头脑风暴；M1 只有占位页 `pages/IdeasPage.vue` |
| `features/workbench/` | 项目工作台外壳：阶段导航、会话选择、对话面板、快照时间线；纯逻辑抽成 `.ts`（`turnControls`、`stageStatus`、`snapshotSelection`、`snapshotReason`、`optimisticSend` 等）单测 |
| `features/canvas/generic/` | M1 的通用文件画布：文件树 + CodeMirror 编辑器、只读/冲突状态 |
| `features/canvas/animation/`（M2） | 动画阶段专属画布：镜头列表（`SceneList.vue`）、代码编辑器、关键帧提示（`KeyframeStrip.vue`）、成片面板（`FinalRenderPanel.vue`：渲染/进度/播放器/定稿） |
| `features/canvas/<topic\|narrative>/`（M3/M4） | 尚未实现 |
| `features/settings/`（M5） | 模型配置、风格库、TTS 音色；M1 只有占位页 `pages/SettingsPage.vue` |
| `components/ui/` | shadcn-vue 生成的组件（通过 CLI 添加，尽量不手改） |
| `components/ai-elements/` | @ai-elements 生成的组件（通过 CLI 添加，尽量不手改） |
| `components/CodeEditor.vue`（+ `codeEditorLanguage.ts`） | 手写的 CodeMirror 封装，M1 起在 `features/canvas/generic/`，M2 T12 挪到这里（决策记录 D36）：`animation` 画布要复用它，而 `features/*` 之间不许互相 import |

规则：`features/*` 之间不互相 import，共用的内容放进 `components/` 或 `composables/`。`components/` 不 import `features/` 或 `pages/`。`pages/` 可以 import `features/`（组合层）。由 `frontend/eslint.config.ts` 中的 `no-restricted-imports` 规则检查（T11 接入；未用 `eslint-plugin-boundaries`；`components/ui`、`components/ai-elements` 下的生成代码整体不做 lint）。

## 4. 进程与数据流

```
浏览器 ──HTTP/SSE──▶ api 进程（FastAPI + agent 会话 + 预览渲染）
                        │   ▲
                SQLite  │   │  jobs 进度轮询
                        ▼   │
                     worker 进程（成片渲染）
两个进程共用：data/studio.db、data/blobs/、data/projects/<id>/
```
