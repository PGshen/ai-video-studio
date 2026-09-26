# Studio：对话式 AI 知识视频工作台 — 架构设计

- 日期：2026-09-26
- 状态：已批准（2026-09-26）
- 代号：`studio`（独立仓库 `ai-video-studio`，与旧项目 `../ai-video` 完全隔离）

## 1. 背景与目标

现有系统的流程是 选题 → 叙事脚本 → 动画代码 → 视频渲染。其中前三步由 AI 一次性生成，问题要到下一环节审核时才会暴露，质量难以把控。

**目标**：让每个 AI 环节都能以对话式交互反复打磨，每一步都交付尽可能高质量的产出。

**已确认的前提：**

| 项 | 决定 |
|---|---|
| 使用规模 | 单人本地使用，偶尔一两个协作者；单机部署 |
| 整体流程 | 保持不变，但把渲染并入动画阶段：**选题打磨 → 叙事 → 动画（代码 + 成片）** |
| 对话形态 | 画布式：agent 直接修改产物文件，右侧实时显示；每轮自动快照，可回滚、可对比；用户可手动编辑 |
| 阶段关系 | 严格分阶段，每个阶段只改自己的产物；下游可以提出"回退建议" |
| 选题形态 | 选题池（头脑风暴，产出想法卡片）+ 项目内"选题打磨"阶段（产出选题简报） |
| Agent 运行时 | Claude Agent SDK（Claude 模型）+ OpenAI Agents SDK（GPT，以及通过 LiteLLM 或 OpenAI 兼容接口接入的 DeepSeek、豆包等）。运行时由所选模型决定，会话中途不切换 |
| 代码阶段反馈 | 视觉自检：agent 渲染单个镜头的预览并查看关键帧 |
| 历史数据 | 不迁移；数据模型重新设计 |
| 基础设施 | 去掉 Temporal、Postgres、MinIO；使用 SQLite 和本地文件 |
| 前端 | Vue 3 + Tailwind CSS + shadcn-vue（含 @ai-elements），以 `dashboard-01` 作为外壳 |
| 渲染引擎 | 保留引擎接口，第一版只实现 manim |
| 联网搜索 | 可插拔的搜索提供方，先接 Tavily |

**非目标**：多租户和权限体系、remotion 引擎、迁移历史数据、会话中途切换运行时。

## 2. 整体架构

### 2.1 进程

| 进程 | 入口 | 职责 |
|---|---|---|
| `api` | `backend/src/studio/main.py` | FastAPI 接口；SSE 推送；agent 会话运行；镜头预览渲染（asyncio 子进程，有并发上限） |
| `worker` | `backend/src/studio/worker.py` | 领取 `jobs` 表中的成片渲染任务，写回进度、心跳和结果 |

两个进程之间只通过 SQLite 和数据目录通信，没有其他中间件。

- api 和 agent 在同一进程，agent 事件通过内存中的会话总线直接推给 SSE。
- worker 的任务进度由 api 每秒轮询一次 `jobs` 表。
- 服务只绑定 `127.0.0.1`，**不做鉴权**。如果以后需要远程访问，再加一个可选的 token 环境变量。

### 2.2 目录

```
ai-video-studio/
  backend/
    pyproject.toml              # uv 管理
    src/studio/
      main.py                   # api 进程入口
      worker.py                 # worker 进程入口
      config.py                 # 数据目录、模型 key、搜索 key 等
      db/                       # SQLite 连接（WAL）、ORM 模型、迁移
      api/                      # 路由：ideas / projects / sessions / files / jobs / settings
      agent/                    # 运行时抽象、会话总线、TurnRunner、Claude/OpenAI/Fake 适配器、ToolSpec
      stages/                   # brainstorm / topic / narrative / animation
                                #   每个阶段：prompt.md、专属工具、产物 schema、校验器、定稿逻辑
      workspace/                # 工作区布局、快照库、diff、回滚、越界检查
      engines/                  # 从现有代码迁移：render（manim）、tts
      search/                   # 搜索提供方接口 + Tavily 实现
      jobs/                     # SQLite 任务队列
    tests/
  frontend/                     # Vue 3 + Vite + TS
  data/                         # 默认数据目录（加入 .gitignore，可用环境变量改到别处）
    studio.db
    openai_sessions.db          # OpenAI Agents SDK 的 SQLiteSession 存储
    claude/                     # Claude Agent SDK 的会话存储目录
    blobs/<hash>                # 快照内容（按内容寻址）
    projects/<project_id>/      # 项目工作区
```

### 2.3 运行环境

- **主要方式**：在宿主机直接运行。Mac 上用 `uv` 和 `pnpm`，manim 所需的 cairo、pango、ffmpeg、LaTeX 用 brew 安装。`make dev` 同时启动 api、worker 和前端三个进程。
- **可选方式**：Docker，一个镜像跑两个后端进程，供老旧 glibc 主机使用。
- **热重载约束**：uvicorn 的 reload 只监听 `backend/src`。数据目录**绝不能**在监听范围内，否则 agent 每写一个文件就会触发一次进程重启。

### 2.4 可从现有代码迁移的资产

| 资产 | 来源 | 在新系统中的角色 |
|---|---|---|
| manim 渲染 | `../ai-video/backend/app/engines/render/manim.py` | `engines/render/manim.py`，供预览和成片共用 |
| TTS | `../ai-video/backend/app/engines/tts/` | `engines/tts/` |
| Beat 对齐 | `../ai-video/backend/app/services/beat_aligner.py` | `synthesize_tts` 工具内部使用 |
| 叙事校验 | `../ai-video/backend/app/services/narrative_validator.py` | `validate_narrative` 工具 |
| 代码规则 | `../ai-video/backend/app/codegen_rules.py`、`../ai-video/backend/app/engines/ai/engine_specs/manim.yaml` | 动画阶段提示词和 `validate_scenes` 工具 |
| 镜头校验与合并 | `../ai-video/backend/app/services/strategies/agent_sandbox.py` | `validate_scenes` 工具、镜头合并逻辑 |
| 兜底文件工具 | `../ai-video/backend/app/services/strategies/openai_agent_runtime.py` | 非 OpenAI 模型的最小文件工具集 |
| 风格组件内容 | 旧项目 dev DB 中的 `prompt_components` | 导入 `style_presets` |

迁移方式是**复制后改写**，新系统不 import 旧代码。完整映射见 [legacy-assets.md](../references/legacy-assets.md)。

## 3. 数据模型

**原则：产物以工作区文件为准，版本由自建快照库管理；SQLite 只存元数据、对话、快照清单和任务。**

### 3.1 SQLite 表

| 表 | 用途 | 关键字段 |
|---|---|---|
| `ideas` | 选题池卡片 | title, pitch, counterintuitive, tags(json), scores(json：反直觉、可论证、可视化、新鲜度), status(`idea`/`picked`/`archived`), source_session_id, project_id |
| `projects` | 项目 | title, idea_id, current_stage, settings(json：画幅、目标时长、音色、语速、渲染引擎) |
| `project_stages` | 各阶段状态 | project_id, stage(`topic`/`narrative`/`animation`), status(`locked`/`active`/`finalized`/`stale`), finalized_snapshot_id, based_on_snapshot_id, finalized_at |
| `sessions` | 对话会话 | project_id（头脑风暴会话为空）, stage(`brainstorm`/`topic`/`narrative`/`animation`), model_profile_id, runtime(`claude`/`openai`), sdk_ref, status(`idle`/`running`/`interrupted`), is_active, title |
| `turns` | 一轮对话 | session_id, user_message, status(`queued`/`running`/`done`/`failed`/`cancelled`/`interrupted`/`budget_exceeded`), start_snapshot_id, end_snapshot_id, usage(json), cost_usd, error |
| `turn_events` | 一轮内持久化的事件 | turn_id, seq, type(`text`/`tool_call`/`tool_result`/`snapshot`/`suggestion`/`notice`/`error`), payload(json) |
| `snapshots` | 工作区快照 | project_id, manifest(json：`{相对路径: sha256}`), reason(`turn`/`user_edit`/`rollback`/`partial`/`init`), turn_id, created_at |
| `suggestions` | 回退建议 | project_id, from_stage, to_stage, content, status(`open`/`applied`/`dismissed`), turn_id |
| `jobs` | worker 任务 | type(`final_render`), project_id, payload(json), status(`queued`/`running`/`done`/`failed`), progress, heartbeat_at, result(json), error |
| `model_profiles` | 模型配置 | name, provider, model, runtime, base_url, api_key_env, supports_vision, price_input, price_output, max_cost_per_turn, max_steps_per_turn |
| `style_presets` | 风格库 | name, category, content(markdown), exemplars(json) |
| `settings` | 键值配置 | 各阶段的默认模型等 |

说明：

- 同一个阶段可以有多个会话（例如换模型时新开），但同一时刻只有一个 `is_active`。会话之间通过工作区文件交接，新会话的首轮前言会附上一份交接摘要。
- 文本增量（token 级）只在内存中推给 SSE，不落库。落库的是合并后的文本块、工具调用和工具结果（结果过长时截断）。
- 表之间不设外键约束，关联在应用层维护。

### 3.2 工作区布局

```
projects/<id>/
  style/STYLE.md                    # 创建项目时从风格库复制
  topic/brief.md                    # 选题简报
  topic/notes/                      # 调研笔记、出处
  narrative/narrative.json          # 由 agent 编写：镜头与 beats
  narrative/timing.json             # 由工具生成：音频哈希、时长、逐字时间戳、beat 时间
  animation/scenes/<scene_id>.py    # 每个镜头一个文件
  .cache/                           # 不参与快照；按内容哈希寻址
    audio/<hash>.mp3
    render/<hash>.mp4
    frames/<hash>/*.png
  output/final.mp4                  # 不参与快照
  output/final.json                 # 成片对应的 snapshot_id 和各镜头哈希
  upstream/<stage>/                 # 上游定稿版本的只读副本；每轮开始前刷新，不参与快照
```

### 3.3 快照库（内容寻址，不使用 git）

不用 git 的原因：agent 开放了 Shell，工作区里如果有 `.git`，agent 可能自行执行 `git commit/reset/checkout`，破坏版本历史。自建快照库放在工作区之外，agent 看不到也改不了，而且快照元数据和 turn、定稿状态可以在同一个 SQLite 事务里写入。

| 操作 | 实现 |
|---|---|
| 扫描 | 遍历工作区（排除 `.cache/`、`output/`、`upstream/`），得到 `{路径: sha256}` |
| 创建快照 | 扫描后，把新内容写入 `data/blobs/<hash>`（已存在则跳过），插入 `snapshots` 行。和上一份清单相同时不新建 |
| 检测变化 | 对比当前扫描结果和最近一份清单 |
| 对比 | 两份清单求差集，得到新增、删除、修改的文件；文本文件用 `difflib` 生成统一 diff |
| 回滚 | 按目标清单写回文件，删除清单之外的文件，再以 `reason=rollback` 新建快照（回滚本身也可撤销） |
| 读历史版本 | 按清单从 blob 读取，用于上游定稿版本的只读访问 |

工作区只包含几十个文本文件，每轮全量扫描和计算哈希的开销可以忽略。

## 4. Agent 运行时

### 4.1 统一接口

```
AgentRuntime.run_turn(ctx: TurnContext) -> AsyncIterator[AgentEvent]

TurnContext:  system_prompt, user_input（文本 + 可选图片）, tools: list[ToolSpec],
              workdir, model_profile, resume_ref, cancel_token, budget
AgentEvent:   TextDelta | TextBlock | ToolCall | ToolResult | Usage | TurnEnd(resume_ref, status)
```

| | ClaudeRuntime | OpenAIRuntime | FakeRuntime |
|---|---|---|---|
| SDK | Claude Agent SDK | OpenAI Agents SDK | 无（用于测试） |
| 业务工具 | 通过 `create_sdk_mcp_server` 转成进程内 MCP 工具 | 转成 `FunctionTool` | 按脚本调用 |
| 会话恢复 | `resume=session_id`；会话存储放在 `data/claude/` | `SQLiteSession`，存在 `data/openai_sessions.db` | — |
| 上下文增长 | SDK 自动压缩 | 保留最近 N 轮；更早的现状由上下文前言兜底 | — |
| 取消 | `interrupt()` | 取消运行中的 task | 立即结束 |

`turn_events` 用于界面展示和回放；SDK 的会话存储用于模型记忆。两者各自独立，不做同步。

### 4.2 工具分层：优先原生，兜底最小集

| 能力 | Claude 模型 | OpenAI 模型（Responses API） | 其他模型（LiteLLM / Chat Completions） |
|---|---|---|---|
| 文件读写 | 原生 Read / Write / Edit / Glob / Grep | 原生 `ApplyPatchTool`（我们实现一个很薄的 `ApplyPatchEditor`） | 兜底：`list_files` / `read_file` / `write_file` / `edit_file` |
| Shell | 原生 Bash，开启 SDK sandbox | 原生 `ShellTool`（本地 executor，工作目录为工作区） | 不提供 |
| 联网（仅 brainstorm / topic） | 原生 WebSearch / WebFetch | 托管 `WebSearchTool` | 兜底：`web_search` / `fetch_url`，接 Tavily |
| 业务工具 | 统一的 `ToolSpec` | 同左 | 同左 |

业务工具定义方式：

```
ToolSpec: name, description, input_model（Pydantic）, stages（可用阶段）,
          handler(ctx, args) -> ToolResult(text, images[], is_error)
```

工具的异常一律转成 `is_error=True` 的结果返回给 agent，不会让这一轮失败。

### 4.3 权限边界

| 阶段 | 可写 | 只读 |
|---|---|---|
| brainstorm | 无（通过 `create_idea`/`update_idea` 写入 `ideas` 表） | 选题池 |
| topic | `topic/` | `style/` |
| narrative | `narrative/narrative.json`（`timing.json` 只能由工具写） | `style/`，以及选题简报（定稿版本） |
| animation | `animation/scenes/` | `style/`，以及叙事（定稿版本） |

上游产物一律读**定稿快照的版本**。在一轮开始前，TurnRunner 把上游定稿内容物化到工作区的只读副本，路径为 `upstream/<stage>/`，不参与快照；每轮都会刷新。这样原生文件工具可以直接读取，不需要额外的工具。

两道防线：

1. **事前拦截（尽力而为）**：Claude 侧通过 `PreToolUse` hook 检查 Write/Edit 的目标路径；OpenAI 侧在 `ApplyPatchEditor` 和兜底文件工具里检查。越界时返回错误说明。
2. **事后兜底（强制）**：本轮结束、创建快照之前，对比本轮前后的扫描结果。凡是落在本阶段可写范围之外的改动（包括通过 Shell 做的改动），都还原为本轮开始时的内容，并在下一轮前言里告知 agent。
3. **工具托管文件**：`narrative/timing.json` 这类由工具生成的文件，不在 agent 的可写范围内，事前拦截会阻止 agent 直接改写。事后检查时，TurnRunner 以本轮工具最后一次写入的内容为准：如果文件内容与工具写入记录不一致，就恢复为工具写入的版本。

### 4.4 一轮对话的生命周期（TurnRunner）

1. `POST /sessions/{id}/messages` 创建 turn。同一会话同一时刻只允许一个运行中的 turn；整个进程另有全局并发上限。
2. 检测工作区变化。如果有未快照的改动，先以 `reason=user_edit` 创建快照。
3. 刷新 `upstream/` 只读副本。
4. 构建**上下文前言**，放在用户消息之前：
   - 自上一轮以来用户手动修改的文件（附 diff 摘要）；
   - 上游是否有新定稿（附按镜头 id 整理的变更摘要）；
   - 上一轮被还原的越界改动；
   - 回滚通知；
   - 当前产物状态摘要（例如各镜头的校验和渲染状态）。
5. 调用 `run_turn`：事件推到会话总线；文本块和工具调用落库；每次文件类工具调用后，推送 `workspace_changed {paths}`。
6. 结束时执行越界检查，创建快照（`turn`，出错时为 `partial`），更新 turn 的状态、用量和成本。
7. SSE：`GET /sessions/{id}/stream?after_seq=`，先回放已落库的事件，再接实时流。
8. 进程启动时，把所有 `running` 的 turn 改为 `interrupted`，对应会话的状态也设为 `interrupted`。

## 5. 各阶段设计

**通用约定：agent 只写内容，派生数据（时长、时间戳、渲染结果）由工具生成。**

### 5.0 头脑风暴（选题池）

- **目标**：发散，批量产出想法卡片。
- **工具**：联网搜索、`list_ideas`（查重）、`create_idea`、`update_idea`。
- **产物**：`ideas` 表中的行。选中卡片后即可创建项目：初始化工作区，复制所选风格为 `style/STYLE.md`，创建初始快照，topic 阶段设为 `active`。

### 5.1 选题打磨（topic）

- **输入**：想法卡片、`STYLE.md`、项目设置。
- **产物**：`topic/brief.md`，章节固定：核心问题；钩子与反直觉点；目标观众与前置知识；关键事实（每条附出处和把握程度）；叙事角度与结构草图；可视化机会；风险点。调研材料放在 `topic/notes/`。
- **工具**：联网搜索和抓取、`check_brief`（检查章节是否齐全、关键事实是否都有出处）。
- **定稿条件**：`check_brief` 没有错误（警告不阻止定稿），由用户确认。

### 5.2 叙事（narrative）

- **输入**：选题简报定稿版本、`STYLE.md`、项目设置。
- **产物**：
  - `narrative.json`（由 agent 编写）：`scenes[]`，每个镜头包含 `id`（稳定的 slug，例如 `s-hook`）、`narration`、`visual_intent`、`beats[]`。每个 beat 包含 `cue_text`、`visual_action`、`emphasis`、`transition`（`continue`/`transform`/`reveal`/`replace`/`exit`）。
  - `timing.json`（由工具生成）：每个镜头的音频哈希（由旁白、音色、语速决定）、时长、逐字时间戳、beat 起止时间、对齐覆盖率。
- **工具**：`validate_narrative`、`synthesize_tts(scene_ids)`、`suggest_upstream_change`。
- **定稿条件**：校验通过；每个镜头的配音都是最新的（音频哈希和当前旁白一致），且对齐覆盖率达到阈值。

### 5.3 动画（animation：代码 + 成片）

- **输入**：叙事定稿版本（`narrative.json` + `timing.json`）、`STYLE.md`、manim 引擎约束。
- **产物**：`animation/scenes/<scene_id>.py`。沿用现有"各镜头代码合并到同一个 Scene 类"的约定，因为镜头之间存在依赖。
- **工具**：
  - `validate_scenes`：静态校验。
  - `render_preview(scene_id)`：低清渲染单个镜头（带必要的前置镜头上下文），在每个 beat 结束时刻抽取关键帧，以图片返回；同时给出渲染时长和配音时长的偏差。模型不支持图片输入（`supports_vision=false`）时，只返回文本指标。单个镜头超时 120 秒。
  - Shell（按运行时提供）：查 API、跑小段试验代码。
  - `suggest_upstream_change`：向叙事阶段提出回退建议。
- **成片**：用户点击"渲染成片"，创建 `final_render` 任务。worker 以最终画质逐个渲染镜头（缓存键为代码、音频、画质和引擎版本的哈希），合成音频，拼接，加字幕，输出 `output/final.mp4` 和 `output/final.json`。
- **定稿条件**：`final.json` 记录的快照等于当前最新快照，由用户确认"成片定稿"。定稿后项目标记为完成。

### 5.4 定稿、上游变更与回退建议

- **定稿**：写入 `finalized_snapshot_id`；下游阶段如果是 `locked`，就变为 `active`，并记录 `based_on_snapshot_id`。
- **重新打开上游**：已定稿的阶段可以继续对话和编辑，状态回到 `active`。在它重新定稿前，下游仍然读上一次定稿的版本。
- **重新定稿后**：如果下游的 `based_on_snapshot_id` 和新的定稿快照不同，下游标记为 `stale`。下游的下一轮前言会附上变更摘要。叙事→动画按镜头 id 对比，列出新增、删除、旁白变化、beat 变化的镜头。下游这一轮结束后，更新 `based_on_snapshot_id`，状态恢复为 `active`。
- **回退建议**：由 `suggest_upstream_change` 写入 `suggestions`，在对话流中显示为卡片，并在阶段导航上显示角标。点击"去处理"会跳转到上游阶段，并把建议内容预填到输入框；处理后标记为 `applied`，也可以 `dismissed`。

### 5.5 提示词

- 每个阶段的系统提示词是 `stages/<stage>/prompt.md`，随代码版本管理。
- 风格通过 `style/STYLE.md` 提供，agent 自行读取。风格库支持附带范例（金样本）。
- 现有风格组件的编写经验写进动画阶段的提示词：必须有布局骨架、图标克制、转场不留中间态、避免角落堆放元素。

## 6. 前端

### 6.1 技术栈

Vue 3、Vite、TypeScript、Tailwind v4、shadcn-vue（含 @ai-elements 的 Conversation / Message / PromptInput / Tool / CodeBlock 等）、TanStack Query（Vue）、vue-router、CodeMirror 6、基于 fetch 的 SSE 客户端（支持 `after_seq` 续传）。外壳用 `npx shadcn-vue@latest add dashboard-01` 初始化。

### 6.2 页面

| 路由 | 内容 |
|---|---|
| `/ideas` | 选题池卡片网格；右侧头脑风暴对话抽屉；卡片上有"创建项目" |
| `/projects` | 项目列表 |
| `/projects/:id/:stage` | 项目工作台 |
| `/settings/*` | 模型配置、风格库（含范例）、TTS 音色 |

### 6.3 项目工作台

```
┌────────────────────────────────────────────────────────────────────┐
│  选题 ✓  ─  叙事 ●  ─  动画 ⚠上游已变更          [定稿] [渲染成片]  │
├──────────────────────────┬─────────────────────────────────────────┤
│ 会话：Claude Opus ▾  [+新会话] │           画布（按阶段切换）           │
│  消息流 / 工具调用（可折叠）    │                                         │
│  关键帧缩略图 / 回退建议卡片    │                                         │
│ [输入框]      [停止/继续]    ├─────────────────────────────────────────┤
│                          │ 快照时间线：… [对比] [回滚到此]               │
└──────────────────────────┴─────────────────────────────────────────┘
```

| 阶段 | 画布 |
|---|---|
| 选题 | `brief.md` 渲染视图和编辑模式；笔记文件列表 |
| 叙事 | 镜头卡片列表（旁白、beats、校验标记、带 beat 刻度的音频播放条）；行内编辑；原始 JSON 标签页 |
| 动画 | 镜头列表（已渲染、已过期、校验失败）；当前镜头的代码编辑器、预览视频、关键帧条；成片面板（进度和播放器） |

### 6.4 协作规则

- 收到 `workspace_changed` 事件后，让对应的文件查询失效，重新拉取。
- agent 运行时画布只读；一轮结束后恢复可编辑。保存时通过 `PUT /projects/:id/files/*path` 直接写文件，后端同样执行本阶段的写入权限检查。
- 回滚会新建快照，对话继续使用；下一轮前言会告知 agent。

## 7. 错误处理

**原则：产物永远不丢。** 任何结束方式都会先创建快照，再更新 turn 状态。

| 场景 | 处理 |
|---|---|
| 模型或网络报错、被限流 | turn 标记为 `failed`，快照为 `partial`；显示错误和"重试" |
| 超出预算（步数或成本） | 平稳停止，状态为 `budget_exceeded`；用户可以说"继续" |
| 用户停止 | 中断，状态为 `cancelled` |
| api 进程重启 | `running` 改为 `interrupted`；显示"继续"，通过 SDK 恢复会话 |
| 工具执行出错 | 作为工具错误结果返回给 agent，让它自行修复 |
| 预览渲染超时 | 杀掉子进程，作为工具错误返回 |
| 越界写入 | 事后还原，并在下一轮前言中告知 |
| 成片任务失败 | 任务标记为 `failed`，附日志末尾和出错的镜头 id；提供"把错误发给 agent" |
| worker 崩溃 | 心跳过期的 `running` 任务，在 worker 启动时标记为失败，可以手动重试 |
| SQLite 繁忙 | WAL 模式，`busy_timeout=5000`，所有写操作使用短事务 |
| 缓存文件缺失 | 重新生成 |

## 8. 测试策略

- **单元测试**：快照库（扫描、创建、diff、回滚、去重）、越界检查与还原、权限规则、各阶段校验器、按镜头 id 对比叙事、缓存键、任务领取与心跳。
- **运行时契约测试**：用 `FakeRuntime` 端到端测试 TurnRunner（前言构建、事件落库、SSE 回放、快照、中断恢复）。两个真实适配器用 mock 的 SDK 测试事件转换。
- **真实冒烟测试**（需显式开启并提供 key）：每种运行时跑一轮最小对话，覆盖写文件、调用业务工具、工具返回图片。
- **渲染集成测试**（慢测试）：渲染一个极小的 manim 镜头并抽取关键帧。
- **API 测试**：临时数据目录和临时 SQLite。
- **前端**：vitest 测 SSE 客户端和状态逻辑；界面在浏览器中手动验收。

## 9. 风险与早期验证项（M1 完成）

| # | 风险 | 验证方式 | 不成立时的对策 |
|---|---|---|---|
| R1 | `ApplyPatchTool`/`ShellTool` 在 LiteLLM 接入的模型上不可用 | 冒烟测试 | 自动改用兜底文件工具集，不提供 Shell |
| R2 | 函数工具返回图片（`ToolOutputImage`）在部分模型上不可用 | 冒烟测试 | 改为"文本说明 + 把图片作为下一条输入消息" |
| R3 | Claude Agent SDK 的 sandbox 在 macOS 本地行为和预期不符 | 手动验证 | 关闭 Bash，只靠事后防线 |
| R4 | Claude SDK 会话存储目录无法指向数据目录 | 手动验证 | 接受默认位置，并在文档中说明 |
| R5 | 原生工具读取 `upstream/` 只读副本时，agent 仍然尝试写入 | 契约测试 | 事前拦截会返回错误；事后防线兜底 |

## 10. 实施顺序

每个里程碑都能独立运行和验收；每个里程碑单独编写实施计划。

1. **M1 骨架**：后端骨架、SQLite 和迁移、快照库、运行时抽象（Claude / OpenAI / Fake）、TurnRunner、SSE；前端外壳、通用的"对话 + 文件画布"；完成 R1–R5 的验证。
2. **M2 动画阶段**：用手工准备的叙事 fixture 作为输入；动画 agent、`validate_scenes`、`render_preview`（含关键帧）、worker 成片、成片定稿。
3. **M3 叙事阶段**：`narrative.json`/`timing.json`、TTS 与 beat 对齐、叙事画布；接上 M2，并实现叙事→动画的上游变更处理。
4. **M4 选题**：选题打磨阶段、选题池与头脑风暴、搜索提供方接口与 Tavily。
5. **M5 完善**：设置页、风格库与范例、回退建议的完整体验、从 dev DB 导入风格组件。
