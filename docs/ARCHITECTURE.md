# ARCHITECTURE：模块地图与分层规则

完整设计见 [design/2026-09-26-architecture.md](design/2026-09-26-architecture.md)。本文件只描述**代码结构**和**依赖方向**，内容必须和代码保持一致（SOP §10）。
下面的分层规则写成了 import-linter 契约（`backend/pyproject.toml` 的 `[tool.importlinter]`），由 `make check` 强制检查。

> 状态：M5 收尾时按实际代码更新（2026-09-30）。

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
| `db` | SQLite 连接（WAL）、ORM 模型、迁移；仓储 `db/repo/*`（M5 新增 `settings`：带类型的键、补丁语义、`effective_web_mode`；`style_presets`：skill 形态目录的校验纯函数与 CRUD；`profiles` 增改删含内置保护与引用检查）；`db/legacy_styles.py`：旧项目风格库的导入转换与命令行（只读导出的 JSON → 风格库，幂等，不 import 旧代码） | `config` |
| `engines.render` | manim 渲染：静态校验、全画质渲染（`manim/{script,process,engine}.py`）、预览与关键帧抽取（T2） | `config` |
| `engines.tts` | Volcengine 语音合成（`base`/`voice_map`/`volcengine`/`factory`，M3 T1）；beat 对齐（T2） | `config` |
| `search` | 搜索提供方协议（`base`：`SearchProvider`/`SearchHit`/`ExtractedPage`/`SearchError`）与 Tavily 实现（`tavily`、`factory`；key 走裸环境变量 `TAVILY_API_KEY`，不进 `Settings`）；纯能力层，有独立的 import-linter 契约 | `config` |
| `workspace` | 工作区布局（`layout`）、快照库与 diff/回滚（`snapshot`、`blobs`）、越界检查（`scope`）、上游只读副本（`upstream`）、受控文件读写与建/删工作区（`files`）；**风格目录渲染**（M5：`style_files.render_style_files`，把风格预设渲染成 `style/` 下的文件映射，纯函数） | `db`、`config` |
| `jobs` | SQLite 任务队列：`create_job`/`claim_next`/`heartbeat`/`update_progress`/`complete`/`fail`/`get_job`/`list_jobs`/`reap_stale_running`；`jobs.repo` 转发自 `db.repo.jobs`（`Job` 模型的直接读写按规则 5 留在 `db.repo`） | `db`、`config` |
| `agent` | 事件（`events`）、`ToolSpec`（`tools`）、运行时协议与注册表（`runtime`）、**阶段定义协议与注册表（`stage`）**、**阶段流转：定稿/重新打开/stale（`stage_flow`）**、会话总线（`bus`）、上下文前言（`preamble`）、TurnRunner（`runner`：公开接口、排队调度、`_persist`/`_publish` 等总线基础方法；一轮生命周期的其余部分拆到同包内的 `turn_state`——`_Job`/`_State` 共享结构、`turn_events`——运行时事件落库与推送、`turn_finish`——收尾（越界检查/快照/写状态）、`recovery`——重启恢复，见 TD-15）、Claude/OpenAI/Fake 适配器（`claude_runtime` 中环境变量拆到 `claude_env`，读写范围 hook 与 Bash sandbox 配置拆到 `claude_scope`，`native` 联网模式下 `WebFetch`/`WebSearch` 的「URL 来源」hook 在 `claude_web`（规则本体在 `url_source`，自建 `fetch_url` 共用），两条沙箱共用的主目录拒读清单在 `sandbox_paths`，SDK 消息转换与业务工具桥接拆到 `claude_messages`；`openai_runtime` 中 `LocalShellExecutor` 拆到 `shell`（经 macOS `sandbox-exec` 执行，Seatbelt 配置生成与平台判断在 `shell_sandbox`），业务工具桥接与 item→事件转换拆到 `openai_tools`）、兜底文件工具与 `ApplyPatchEditor`；**无项目会话**（M4：`StageDefinition.workspaceless`，头脑风暴走无工作区模式，cwd 是每轮开始前重建、一轮结束即删的 scratch 目录 `data/scratch/<session_id>/`（进程启动时清掉遗留），没有快照/`upstream/`/越界检查，`_Job.busy_key` 让它不阻塞项目 turn）；**联网模式**（`STUDIO_WEB_MODE`：`TurnRunner._tools_and_web` 决定 `allow_web` 和是否滤掉带 `ToolSpec.web` 标志的自建联网工具，模型走不了原生联网时回退到自建工具，见 ADR 0010）；`StageDefinition.finalize_blockers`（api 定稿前检查，topic 返回 `check_brief` 的错误，有错误则 409）；**M5**：联网模式每轮读有效值（界面设置优先，`db.repo.settings.effective_web_mode`）；**会话内换模型**（`turn_events.note_model_switch`：换了之后的第一轮按 `usage.profile_name` 发 `model_switched` notice，`turn_finish` 记录每轮实际用的 `model`/`profile_name`，见 ADR 0012）；**回退建议**（`ToolContext`/`TurnContext` 新增 `turn_id`、`upstream_stages`，`turn_events._announce_suggestions` 在 `suggest_upstream_change` 成功后发持久的 `suggestion` 事件；**thinking 事件**（对话页重做，ADR 0013：`events.ThinkingDelta`/`ThinkingBlock`，`turn_events` 里空白丢弃、不计步数，`thinking_delta` 瞬时、`thinking` 落库；Claude 在 `claude_messages` 转换并设 `thinking=adaptive+summarized`，OpenAI 在 `openai_tools.convert` 转换并在 `provider=openai` 路径设 `reasoning.summary=auto`；`fake` 增加 `think`/`emit` 步骤和 `/demo-activity` 演示脚本）） | `workspace`、`db`、`config` |
| `stages.common` | 各阶段共用的业务工具：`suggest_upstream_change`（写 `suggestions` 表，narrative/animation 用；M5：只能向直接上游提，内容非空且 ≤ 2000 字，记录 `turn_id`）、`web_tools`（`web_search`/`fetch_url`，brainstorm/topic 用；带「URL 来源」限制，见 ADR 0010；`STUDIO_WEB_MODE=native` 时被 TurnRunner 滤掉） | `agent`、`workspace`、`db`、`search`、`config` |
| `stages.<brainstorm\|topic\|narrative\|animation>` | 各阶段的提示词、专属工具、产物 schema、校验器，实现 `agent.stage.StageDefinition`；`animation`（M2）已有完整提示词 + `validate_scenes`/`render_preview` 工具，`narrative`（M3）已有完整提示词 + `validate_narrative`/`synthesize_tts` 工具与产物 schema（`schema.py`），`brainstorm`（M4）没有工作区，工具 `list_ideas`/`create_idea`/`update_idea` 读写 `ideas` 表，联网工具来自 `stages.common`；`topic`（M4）有完整提示词、`brief.py`（`topic/brief.md` 的结构与 `check`）、`check_brief` 工具和联网工具 | `stages.common`、`agent`、`workspace`、`engines`、`search`、`jobs`、`db`、`config` |
| `api` | HTTP 路由、SSE；M5 新增 `settings`（`/api/settings`）、`styles`（`/api/style-presets*`）、`tts`（音色列表、带磁盘缓存与并发合并的真实试听）、`suggestions`（回退建议查询与 `apply`/`dismiss`），`profiles` 增改删，`sessions` 加 `PATCH`（换模型），`projects` 加 `PATCH /settings` 与创建时选风格、复制默认音色/语速 | 以上全部（除 `main`） |
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
| `pages/` | 路由页面（组合层）：`router.ts` 指向这里；可以 import 多个 `features/`，把它们拼成一个页面（`ProjectsPage`、`ProjectWorkbenchPage`、`IdeasPage`、`SettingsPage`：设置页外壳，子导航 + 子路由出口，四个子页 `/settings/{models,styles,voice,general}` 直接指向 `features/settings/` 的面板） |
| `api/` | 类型化的 HTTP 客户端和 SSE 客户端（支持 `after_seq` 续传） |
| `types/` | 与后端 schema 对应的 TS 类型 |
| `composables/` | TanStack Query hooks 和会话流状态；共用的纯逻辑与副作用（`styleChoice`：创建项目选风格；`voiceRules`：语速范围；`useVoicePreview`：试听播放） |
| `features/projects/` | 项目列表、新建项目（`ProjectList.vue`） |
| `features/ideas/`（M4） | 选题池：卡片网格（`IdeaGrid`/`IdeaCard`）、新建/编辑对话框、按卡片创建项目、头脑风暴抽屉（`BrainstormDrawer`，停靠在页面右侧的非模态面板）；纯逻辑在 `ideaView.ts`；页面 `pages/IdeasPage.vue` 组合它们 |
| `features/workbench/` | 项目工作台外壳：阶段导航、会话选择、对话面板、三栏分栏（`WorkbenchSplit`：对话 | 画布 | 快照栏，reka-ui `SplitterGroup`，宽度与折叠状态存 localStorage，窄屏堆叠）、快照栏（`SnapshotRail` → `SnapshotTimeline` 上时间线 + `SnapshotDetail` 下详情与回滚）；纯逻辑抽成 `.ts`（`turnControls`、`stageStatus`、`snapshotSelection`、`snapshotTime`、`snapshotReason`、`optimisticSend` 等）单测 |
| `features/canvas/generic/` | M1 的通用文件画布：文件树 + CodeMirror 编辑器、只读/冲突状态 |
| `features/canvas/animation/`（M2） | 动画阶段专属画布：镜头列表（`SceneList.vue`）、代码编辑器、关键帧提示（`KeyframeStrip.vue`）、成片面板（`FinalRenderPanel.vue`：渲染/进度/播放器/定稿） |
| `features/canvas/narrative/`（M3） | 叙事阶段专属画布：镜头卡片（`SceneCardList.vue`）、按 beat 分段的配音播放条（`BeatTimeline.vue`，音频直接用文件端点的 URL，端点支持 Range）、原始 JSON 标签页；校验标记/配音状态/定稿提示条的纯逻辑在 `narrativeDoc.ts`/`timingStatus.ts` |
| `features/canvas/topic/`（M4） | 选题阶段专属画布：`BriefStatusIcon`（`check_brief` 同一份检查结果的状态图标，悬停/聚焦弹气泡，不禁用定稿按钮）、简报/笔记两个标签、`EditModeToggle`（渲染/编辑图标切换，与状态图标一起在标签行右侧）、`MarkdownFilePane`（一个 Markdown 文件的渲染视图 + 编辑模式 + 冲突处理，简报和笔记共用；模式由 `TopicCanvas` 持有，`v-model:mode`）；检查结果状态和笔记列表的纯逻辑在 `briefStatus.ts` |
| `features/settings/`（M5） | 设置页的四个子页：`ModelProfilesPanel`/`ModelProfileDialog`（模型配置增改删；表单规则 `profileForm.ts` 与后端一致；环境变量决定的字段只读）、`StylePresetsPanel`/`StylePresetEditor`（风格库：按分类分组的列表、文件树 + CodeMirror 编辑器、复制/设默认/删除；草稿与校验 `styleDraft.ts`）、`VoicePanel`（音色列表、试听、新项目默认音色/语速）、`GeneralPanel`（各阶段默认模型、联网模式及风险提示；文案与规则 `settingsView.ts`） |
| `components/session/`（M4 T10） | 会话面板（`SessionPanel`）、会话选择器（`SessionPicker`）、时间线条目（`SessionTimelineItem`）及其纯逻辑（`turnControls`、`optimisticSend`、`snapshotReason`）。项目工作台和头脑风暴抽屉共用，所以从 `features/workbench/` 搬到这里；靠 `composables/sessionScope.ts` 的 `SessionScope`（项目阶段 / 头脑风暴）区分查询和创建接口；**M5**：`ModelSwitcher`（会话内换模型，可选项规则 `modelChoice.ts` 与后端一致，也含新建会话时的默认模型预选）、`SuggestionCard`（回退建议卡片，流程规则 `suggestionFlow.ts`）、`PromptPrefill`（往输入框预填）、`noticeText.ts`（`notice` 文案，含 `model_switched`）；**对话页重做（2026-10-02，设计 [chat-ui-redesign](design/2026-10-02-chat-ui-redesign.md)）**：`SessionTimeline` 把扁平条目流用纯函数 `groupTimeline` 归成「活动组」（同一 turn 连续的思考与工具调用），`activity/` 下是 `ActivityGroup`/`ActivityRow`（可折叠，折叠规则 `useDisclosure`）、`ThinkingBody`、`ToolBody` 按 `toolPresentation.describeTool` 的渲染种类分发到 `tool-bodies/{Read,Write,Glob,Grep,Bash,WebSearch,WebFetch,Generic}Body`（共用 `ToolPane`/`CodeView`/`DiffView`/`ErrorPane`），`ReplyFooter`（用量/用时/时间，`turnMeta`）；助手与思考文本走 Markdown，原始 HTML 先经 `markdownSafe.escapeRawHtml` 转义；搜索结果解析在 `webSearchResult`，Claude `Read` 行号解析在 `readResult` |
| `components/StyleSelect.vue`、`components/VoicePreviewButton.vue`（M5） | 两处入口共用的控件：创建项目时的风格选择器（项目页新建对话框、选题池的「创建项目」对话框）；音色试听按钮（设置页语音页、项目设置对话框；旁边固定写明会产生费用） |
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
