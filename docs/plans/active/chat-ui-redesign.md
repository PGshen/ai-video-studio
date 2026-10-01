# chat-ui-redesign：对话页重做（活动组、工具专属渲染、thinking 事件）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 待验收 |
| 里程碑 | M5 之后的独立改动（无里程碑编号） |
| 设计依据 | [对话页重做设计](../../design/2026-10-02-chat-ui-redesign.md)；事件协议基线见 [架构设计 §3.1、§4](../../design/2026-09-26-architecture.md) |
| 分支 | `chat-ui-redesign` |
| 批准记录 | 2026-10-02：负责人批准设计，并说明 ccproxy 网关因所在网络不通暂不测试；2026-10-02：负责人批准计划，执行方式为当前会话内联 |

> **执行方式**：当前会话内联（2026-10-02 负责人指定）。

## 目标

对话页按参考截图重做：思考与工具调用归入可折叠的「活动组」，组内每条思考、每个工具都能单独折叠；Read / Write / Glob / Grep / Bash / WebSearch / WebFetch 各有专属的请求 + 结果渲染；助手回复渲染 Markdown 并带用量、用时、时间。后端新增 `thinking` 事件，Claude 与 OpenAI 两个运行时都透传。

## 范围

**包含：**

- 后端 `thinking_delta`（瞬时）/ `thinking`（落库、可回放）事件，贯穿 `events` → `turn_events` → `bus` → SSE 白名单；Claude 运行时与 OpenAI 运行时的转换与开启；FakeRuntime 的 `think` / `emit` 脚本步骤和一个演示脚本。
- 前端：`ThinkingItem`、`useSessionStream` 合并与对外暴露 `turns`；`groupTimeline`、`toolPresentation`、`webSearchResult`、`turnMeta` 四个纯函数；活动组 / 行 / 各工具正文组件；助手 Markdown、用户气泡时间、回复操作栏。
- 真实模型冒烟：Claude 本机登录、OpenAI（经 OpenRouter）各跑一轮，确认实际有 thinking 内容；结论写进 `docs/references/`。
- ADR（`thinking` 事件与「尽力透传、不加开关」）、ARCHITECTURE / glossary / QUALITY 更新。

**不包含：**

- 经 ccproxy 网关的任何测试（负责人当前网络不通；`claude-sonnet` 网关配置不验证）。
- 输入框改版；点赞/点踩、分支；设置页 thinking 开关；业务工具（`write_ideas`、`validate_scenes`、`render_preview` 等）的专属渲染（走通用样式）。
- `ai-elements/tool/*`、`ai-elements/message/*` 等生成代码的修改（新组件不依赖 `tool/*`；最终无引用时才在 T10 删除并登记）。
- 数据库迁移（`turn_events.type` 是自由字符串）。

## 全局约束

每个任务都隐含满足：

- 红线（AGENTS.md）：不改 `../ai-video`；不用 `skip`/`xfail`/`# type: ignore`/`noqa` 绕过失败；不引入计划外的新依赖（`shiki`、`vue-stream-markdown`、`@lucide/vue`、`@vueuse/core` 已在 `frontend/package.json`）；不改 `docs/design/2026-09-26-architecture.md`；工作区 `data/` 不进 uvicorn reload 监听。
- 测试先行：每个任务先写失败的测试并确认失败，再实现。
- 前端遵守 `eslint.config.ts` 的分层规则；单个 `.vue` 约 250 行以内；纯逻辑放 `.ts` 并配 `.spec.ts`。
- 面向用户的文案用中文，代码标识符与注释用英文；提交格式 `<type>(<scope>): <中文说明>`；代码与计划更新放同一个 commit。
- 每个任务结束时 `make check` 为绿。
- 真实模型测试优先用本机 Claude 登录（`make smoke SMOKE_ARGS="-k claude_login"`），不限次数；OpenAI/OpenRouter 用例沿用 smoke 预授权的成本上限（见 `tests/smoke/test_smoke.py` 的 `COST_LIMITS`）；**不跑 ccproxy 网关用例**。

## 验收标准

- [x] AC1：`ThinkingDelta` 只发布（`thinking_delta`）、`ThinkingBlock` 落库（`thinking`）并出现在 SSE 回放；不计入步数与预算。（验证：`tests/agent/test_runner.py`、`tests/api/test_stream.py` 新增用例）
- [x] AC2：Claude 运行时把 `thinking_delta` 流事件和 `ThinkingBlock` 转成 thinking 事件，子 agent 的 thinking 被丢弃，空文本不产生事件；`ClaudeAgentOptions.thinking` 已设置。（验证：`tests/agent/test_claude_runtime.py`）
- [x] AC3：OpenAI 运行时把 `response.reasoning_summary_text.delta` 与 `ReasoningItem` 摘要转成 thinking 事件；`model_settings` 带 `reasoning.summary="auto"` 且不破坏既有 `store=False` / `response_include` 断言。（验证：`tests/agent/test_openai_runtime.py`）
- [x] AC4：真实模型实测——Claude 本机登录与 OpenAI（OpenRouter）各一轮，记录是否出现 thinking 文本及内容形态；结论写入 references，证据文件在 `data/evidence/`。（验证：`make smoke` 日志）
- [x] AC5：`groupTimeline` 按设计 §2 分组（同 turn 连续 thinking/tool_call；遇其它条目断开；末尾组标 `running`）；`toolPresentation` 对 7 类工具、两个运行时的名字与参数给出正确的种类与摘要，未知工具走 `generic`；`webSearchResult` 解析自建与 Claude 原生两种格式，失败回退原文。（验证：对应 `.spec.ts`）
- [x] AC6：折叠规则：运行中的末尾组展开、turn 结束或后面出现文本后折叠、历史回放折叠；行默认折叠、出错行展开；用户手动状态优先且不随会话切换串线。（验证：组件测试 + L4）
- [x] AC7：Read / Write(Edit/apply_patch) / Glob / Grep / Bash / WebSearch / WebFetch 的展开正文符合设计 §5 表格；运行中转圈、出错变红、被中断显示「已中断」。（验证：组件测试 + L4 截图）
- [x] AC8：助手回复渲染 Markdown 且不执行模型输出里的 HTML；用户气泡下有时间与复制；回复操作栏显示复制、用量、用时、时间，数据缺失时整行不显示。（验证：组件测试 + L4 截图）
- [ ] AC9：L4——`make dev` 下用演示脚本跑一轮含 thinking 与 7 类工具的对话，并用本机 Claude 登录真实跑一轮；折叠/展开、运行中、出错行截图存证。
- [x] AC10：ADR、references、ARCHITECTURE、glossary、QUALITY 已更新；`make check` 全绿；收尾清单（SOP §7）完成。

## 评审关注点

设计没有明说、但使用者很可能遇到的输入；每条都在对应任务里有测试。

1. 只有空白的 `thinking_delta` / 空 `ThinkingBlock`：不产生条目，不出现空的「已思考」组（T1、T2、T3、T5）。
2. 一个 turn 里 thinking 与文本交替出现多段，且 `thinking_delta` 流式累积后被最终 `thinking` 事件替换、SSE 重连回放不重复（T5）。
3. 工具没有结果但 turn 已结束（取消/崩溃/预算耗尽）：显示「已中断」而不是一直转圈（T6、T8）。
4. 工具参数缺字段或类型异常（`Read` 没有 `file_path`、`Bash` 的 `command` 不是字符串、`shell` 的 `commands` 为空）：摘要退回工具名，正文走通用样式，不抛错（T6、T8）。
5. 超长或被截断的结果（落库上限 8000 字且带 `truncated`、超过 40 行）：限高滚动并提示「已截断」；模型输出含 `<script>` / 原始 HTML 时被转义（T8、T9）。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：thinking 事件贯通后端（完成）

- **目标**：运行时事件、落库、SSE 白名单、总线瞬时集合都认识 thinking；FakeRuntime 能脚本化产出 thinking 和任意工具调用（后续前端 L4 要用）。
- **涉及文件**：`backend/src/studio/agent/events.py`、`agent/turn_events.py`、`agent/bus.py`、`agent/fake.py`、`api/sessions.py`；测试 `backend/tests/agent/test_runner.py`、`tests/agent/test_fake.py`、`tests/api/test_stream.py`、`tests/agent/test_bus.py`（若涉及瞬时集合断言）。
- **接口与要点**：
  - `events.ThinkingDelta(text: str)`、`events.ThinkingBlock(text: str)`，加入 `AgentEvent` 联合。
  - `turn_events.handle`：`ThinkingDelta` → `runner._publish(job, "thinking_delta", {"text"})`；`ThinkingBlock` → `runner._persist(job, "thinking", {"text"})`；二者都不动 `state.steps`。
  - `TRANSIENT_EVENT_TYPES` 加 `"thinking_delta"`；`WIRE_EVENT_TYPES` 加 `"thinking_delta"`、`"thinking"`；同步更新 `sessions.py` 里列出事件种类的文档字符串。
  - `fake.py` 新增步骤 `Think(text)`（产出 `ThinkingDelta` 若干 + 一个 `ThinkingBlock`）与 `Emit(name, args, result_text, is_error=False)`（产出 `ToolCall` + `ToolResult`，`call_id` 沿用 `call-N` 计数），对应构造函数 `think()` / `emit()` 并加入 `FakeStep`。
- **测试**（先写）：
  - runner：脚本 `[think("想一想"), say("好")]` → 持久事件类型含 `thinking`、不含 `thinking_delta`，`state.steps` 为 0；`Think("")` 与全空白文本不产生 `thinking`（评审关注点 1）。
  - stream：`thinking` 在 `after_seq=0` 回放里出现，`thinking_delta` 不在；`WIRE_EVENT_TYPES` 含两者；总线上 `thinking_delta` 属瞬时事件（`seq` 为 `None`，SSE 帧没有 `id`）。
  - fake：`emit()` 产出配对的 `call_id`，`is_error` 透传。
- **完成标准**：上述测试通过；`make check` 为绿。
- **验证命令**：`cd backend && uv run pytest tests/agent tests/api/test_stream.py -q`，然后 `make check`

### T2：Claude 运行时透传 thinking（完成）

- **目标**：Claude SDK 的 thinking 变成 `ThinkingDelta` / `ThinkingBlock`，并在选项里开启。
- **涉及文件**：`backend/src/studio/agent/claude_messages.py`、`agent/claude_runtime.py`（`ClaudeAgentOptions` 构造处，约 `include_partial_messages=True` 附近）；测试 `backend/tests/agent/test_claude_runtime.py`（`TestEventConversion` 与选项构造相关用例）。
- **接口与要点**：
  - `convert_message`：`StreamEvent` 的 `content_block_delta` 且 `delta.type == "thinking_delta"` → `ThinkingDelta(text=delta["thinking"])`（空串不产生）；`AssistantMessage.content` 里的 `claude_agent_sdk.ThinkingBlock` 且 `.thinking.strip()` 非空 → `events.ThinkingBlock`。`parent_tool_use_id` 非空（子 agent）整条丢弃的现有逻辑保持。
  - 选项：`thinking={"type": "adaptive", "display": "summarized"}`（SDK 0.2.160 的 `ThinkingConfigAdaptive`，见 `types.py`）。
  - `signature` 字段不外传、不落库。
- **测试**（先写）：把 `thinking_delta` 流事件、`ThinkingBlock(thinking="…", signature="s")`、空白 thinking、带 `parent_tool_use_id` 的 thinking 各构造一条消息，断言转换结果；断言构造出的 `ClaudeAgentOptions.thinking == {"type": "adaptive", "display": "summarized"}`。
- **完成标准**：测试通过；`make check` 为绿。
- **验证命令**：`cd backend && uv run pytest tests/agent/test_claude_runtime.py -q`，然后 `make check`

### T3：OpenAI 运行时透传 thinking（完成）

- **目标**：Responses 路径与 LiteLLM 路径的 reasoning summary 变成 thinking 事件，并请求摘要。
- **涉及文件**：`backend/src/studio/agent/openai_tools.py`（`convert`）、`agent/openai_runtime.py`（`model_settings`）；测试 `backend/tests/agent/test_openai_runtime.py`。
- **接口与要点**：
  - `convert`：`RawResponsesStreamEvent` 中 `data.type == "response.reasoning_summary_text.delta"` → `ThinkingDelta(text=data.delta)`；`RunItemStreamEvent` 的 `ReasoningItem` → 从 `item.raw_item.summary[*].text` 用换行拼接，非空才产出 `ThinkingBlock`。
  - `model_settings`：两个分支都带 `reasoning=Reasoning(summary="auto")`；网关分支保留 `store=False`、`response_include=["reasoning.encrypted_content"]`。
  - 现有 `test_openai_runtime.py` 中对 `settings.response_include` 的断言（约 413–422 行）必须仍然通过；若有对整个 `ModelSettings` 做相等比较的用例，同步调整并在「决策记录」写明。
- **测试**（先写）：用 `ScriptedModel`（`ModelStep.stream([...])` 手写 reasoning 事件，参考该文件里 shell 调用的写法）驱动一轮，断言先 `ThinkingDelta` 后 `ThinkingBlock`，且之后的文本/工具事件不受影响；空摘要不产生事件；`model_settings` 两个分支都带 `reasoning`。
- **完成标准**：测试通过；`make check` 为绿。
- **验证命令**：`cd backend && uv run pytest tests/agent/test_openai_runtime.py -q`，然后 `make check`

### T4：真实模型实测、ADR 与 references（完成）

- **目标**：确认 thinking 在真实环境里确实有内容；把事实与决策落档。**这是整个计划的风险关口**。
- **涉及文件**：`backend/tests/smoke/test_smoke.py`、`tests/smoke/support.py`（新增 thinking 观测与证据记录）；`docs/references/claude-agent-sdk.md`、`docs/references/openai-agents-sdk.md`；`docs/decisions/0013-thinking事件.md`；`docs/runbooks/verification.md`（补一句如何看 thinking）。
- **接口与要点**：
  - 在现有 Claude 登录用例与 OpenAI（OpenRouter）用例旁各加一个只断言「若有 thinking 则内容非空」并**记录证据**的观测（不因模型这轮没思考而失败——因为设计是尽力透传；但证据里要写明有没有）。
  - 先跑 `make smoke SMOKE_ARGS="-k claude_login"`；再跑 OpenAI（OpenRouter）用例，需要 `backend/.env` 里有对应 key，缺 key 时记录「未验证」而不是失败。**不跑任何经 ccproxy 的用例。**
  - 观察并记录：Claude `summarized` 是否有文本、`thinking_delta` 是否到达；OpenRouter 加 `reasoning.summary` 后是否被接受、多轮回放（`SQLiteSession` + `encrypted_content`）是否仍正常（references 里该点此前标为「未验证」）。
  - ADR 0013：背景（截图要的样式需要思考内容）、决定（新增两个事件、尽力透传、不加开关）、其他方案（per-profile 开关、前端不展示思考）、影响（协议变化、模型不给时无 thinking 条目）。
  - **升级条件**：任一真实环境完全拿不到 thinking 内容、或 OpenRouter 拒绝 `reasoning` 参数/多轮回放报错 → 停下，在「阻塞」写清并问负责人（可选：该运行时降级为不开启并在 ADR 注明）。
- **测试**：smoke 用例本身；`scripts/check_docs.py` 校验新 ADR 与链接。
- **完成标准**：证据文件在 `data/evidence/`（不入库）；references 与 ADR 已写，AC4 逐条有结论；`make check` 为绿。
- **验证命令**：`make smoke SMOKE_ARGS="-k claude_login"`，然后 `make check`

### T5：前端 thinking 条目与会话状态（完成）

- **目标**：`useSessionStream` 认识 thinking，并把 turn 元数据暴露给 UI。
- **涉及文件**：`frontend/src/types/events.ts`、`frontend/src/composables/useSessionStream.ts`、`useSessionStream.spec.ts`。
- **接口与要点**：
  - `events.ts`：`WireEventType` 加 `'thinking_delta' | 'thinking'`；`ThinkingDeltaPayload { turn_id; text; seq: null }`、`ThinkingPayload { turn_id; text; seq: number }`；补进 `WireEventMap`。
  - `ThinkingItem { kind: 'thinking'; turnId: string; text: string; streaming: boolean }` 加入 `TimelineItem`。
  - 合并规则照搬 `text`：`thinking_delta` 追加到末尾同 turn 的流式 thinking，否则新建；`thinking` 替换最近的流式 thinking，找不到就追加。`findLastStreamingTextIndex` 泛化为按 `kind` 查找。
  - `UseSessionStreamResult` 新增 `turns: Ref<ReadonlyMap<string, TurnOut>>`（把内部 `knownTurns` 改为响应式 `Map`，`applyHistory` / `refreshTurnStatus` 写入）；`turnStatus` 行为不变。
  - `src/api/sse.ts` 的事件名白名单若按 `WireEventType` 过滤，同步加入新事件。
- **测试**（先写）：delta 累积 → 最终 `thinking` 替换且 `streaming` 变 `false`；thinking 与 text 交替两段互不覆盖；回放同一 `thinking`（重连）不产生重复条目（评审关注点 2）；空白 delta 不建条目（评审关注点 1）；`turns` 在历史加载和 `refreshTurnStatus` 后有对应 turn。
- **完成标准**：`pnpm exec vitest run` 通过；`make check` 为绿。
- **验证命令**：`cd frontend && pnpm exec vitest run src/composables src/api`，然后 `make check`

### T6：纯函数——分组、工具归类、搜索结果解析、元信息（完成）

- **目标**：把所有可单测的展示逻辑先做成纯函数，组件只做渲染。
- **涉及文件**（均在 `frontend/src/components/session/`，各配 `.spec.ts`）：`groupTimeline.ts`、`toolPresentation.ts`、`webSearchResult.ts`、`turnMeta.ts`。
- **接口与要点**：
  - `groupTimeline(items: TimelineItem[], runningTurnId: string | null): TimelineBlock[]`；`TimelineBlock = TimelineItem | ActivityGroupBlock`；`ActivityGroupBlock { kind: 'activity'; turnId: string; entries: (ThinkingItem | ToolCallItem)[]; running: boolean }`。`running` = 该组是最后一个块且其 turn 等于 `runningTurnId`。仅含空白文本的 thinking 在分组前过滤。
  - `describeTool(item: ToolCallItem, workdirPrefix?: string): ToolView`；`ToolView { kind: 'read'|'write'|'glob'|'grep'|'bash'|'web-search'|'web-fetch'|'generic'; label: string; summary: string; path?: string }`。映射表按设计 §5：`Read`/`read_file`→read；`Write`/`write_file`/`Edit`/`MultiEdit`/`edit_file`/`apply_patch`→write（`label` 区分「写入/编辑/补丁」）；`Glob`/`list_files`→glob；`Grep`→grep；`Bash`/`shell`→bash（摘要取 `description`，否则命令第一行；`shell` 取 `commands[0]`）；`WebSearch`/`web_search`→web-search；`WebFetch`/`fetch_url`→web-fetch（摘要为域名 + 路径）。路径去掉工作区绝对前缀；参数缺失或类型不符时 `summary` 退回工具名、`kind` 退回 `generic`。
  - `parseWebSearch(text: string): { query?: string; hits: { title: string; url: string; published?: string; snippet?: string }[] } | null`：支持自建工具的编号文本（`N. 标题` / 缩进 URL / `发布时间：` / 摘要）与 Claude 原生的 `Links: [{…}]` JSON；其它返回 `null`。
  - `formatTurnMeta(turn: TurnOut | undefined): { tokens?: string; duration?: string; time: string } | null`：`usage` 取 input+output token（`51K`、`1.2M` 缩写）、用时 = `updated_at − created_at`（`6 秒`、`1 分 12 秒`）、时间 `HH:mm`；turn 缺失或未结束（`queued`/`running`）返回 `null`。
- **测试**（先写）：每个函数的正常路径；`groupTimeline` 的断开规则（文本/用户消息/notice 断开、跨 turn 断开、末尾 `running`）；`describeTool` 对 7 类工具 × 两个运行时的表驱动用例，加评审关注点 4 的畸形参数；`parseWebSearch` 两种格式、空结果、乱文本回退；`formatTurnMeta` 边界（用量缺失、跨分钟）。
- **完成标准**：纯函数测试全部通过，覆盖设计 §5 表格每一行；`make check` 为绿。
- **验证命令**：`cd frontend && pnpm exec vitest run src/components/session`，然后 `make check`

### T7：活动组骨架与折叠（完成）

- **目标**：用新组件替换现有逐条渲染，先让 thinking、通用工具的分组与折叠完整可用。
- **涉及文件**：新建 `frontend/src/components/session/SessionTimeline.vue`、`activity/ActivityGroup.vue`、`activity/ActivityRow.vue`、`activity/ThinkingBody.vue`、`activity/ToolPane.vue`（标题栏 + 语言 + 「复制」+ 限高内容区）、`activity/tool-bodies/GenericBody.vue`、`activity/useDisclosure.ts`（折叠状态）；改 `SessionPanel.vue`（用 `SessionTimeline`）、`SessionTimelineItem.vue`（移除 `tool_call` 分支，新增 `thinking` 不在此处理）。
- **接口与要点**：
  - `SessionTimeline` props：`items: TimelineItem[]`、`runningTurnId: string | null`、`turns: ReadonlyMap<string, TurnOut>`、`projectId: string | null`；内部 `groupTimeline` 后遍历。
  - `useDisclosure(sessionId)`：以 `${turnId}:${index}` 为键存「用户是否手动切换过」及其值；`isGroupOpen(group, turnStatus)`、`isRowOpen(entry)` 实现 AC6 规则；`sessionId` 变化时清空（评审：不串线）。
  - 折叠头动画用现有 `ui/collapsible`；`ToolPane` 内容区超过 40 行限高 `max-h-80 overflow-auto`；复制用 `navigator.clipboard`，失败时静默不报错。
  - 工具行运行状态：无结果转圈；`result.isError` 红色；turn 已结束仍无结果 → 「已中断」。
- **测试**（先写，`@vue/test-utils`）：`useDisclosure` 规则（运行中展开、turn 结束折叠、手动优先、会话切换清空）；`ActivityGroup` 组头文案（只有思考 → 「已思考」；有工具 → 「N 次工具调用」；运行中文案）；点击组头与行头可折叠展开；出错行默认展开；无结果且 turn 结束显示「已中断」（评审关注点 3）。
- **完成标准**：测试通过；开发服务器下旧工具卡片已被新组件替代、通用样式可用；`make check` 为绿。
- **验证命令**：`cd frontend && pnpm exec vitest run src/components/session`，然后 `make check`

### T8：七类工具的专属正文（完成）

- **目标**：按设计 §5 渲染每类工具的请求 + 结果。
- **涉及文件**：`activity/tool-bodies/{Read,Write,Glob,Grep,Bash,WebSearch,WebFetch}Body.vue`、`activity/ToolBody.vue`（按 `ToolView.kind` 分发，其余走 `GenericBody`）、各自 spec。先看 `ai-elements/code-block` 能否直接复用做语法高亮；不行就在 `ToolPane` 里直接用 `shiki`（已在依赖里），不新增依赖。
- **接口与要点**：
  - Read：路径标题栏 + 语言（按扩展名）+ 代码块；结果每行都以 `数字→` 或 `数字<Tab>` 开头视为已带行号，否则前端补行号；`truncated` 时末尾「已截断」。
  - Write：`Write`/`write_file` 展示 `content`；`Edit`/`edit_file` 展示 old→new 差异；`apply_patch` 展示 `diff`；结果一行状态。
  - Glob：结果按行变列表；Grep：等宽文本块保留换行。
  - Bash：终端风格（状态点 + 命令 + 输出）；`shell` 的 `commands` 逐条列出；运行中转圈。
  - WebSearch：用 `parseWebSearch` 渲染卡片，`null` 回退原文；WebFetch：URL 链接（`target="_blank" rel="noopener noreferrer"`，仅 `http(s)` 才渲染成链接）+ 正文文本。
  - 空结果显示「（无输出）」；所有结果文本以文本节点渲染，不使用 `v-html`。
- **测试**（先写）：每个正文组件用代表性的 `ToolCallItem`（两个运行时各一份）挂载并断言关键文本、标题栏、复制按钮；Read 自带行号与补行号两种；WebSearch 两种格式 + 回退；WebFetch 的 `javascript:` URL 不渲染为链接；超过 40 行限高且有滚动类；`truncated` 提示（评审关注点 5）。
- **完成标准**：测试通过；`make check` 为绿。
- **验证命令**：`cd frontend && pnpm exec vitest run src/components/session/activity`，然后 `make check`

### T9：消息样式、Markdown 与元信息（完成）

- **目标**：助手回复渲染 Markdown；用户气泡带时间与复制；回复末尾操作栏。
- **涉及文件**：`SessionTimelineItem.vue`、新建 `activity/ReplyFooter.vue`、`SessionTimeline.vue`（把 turn 最后一条助手文本后插入 `ReplyFooter`）；复用 `ai-elements/message/MessageResponse.vue`（`vue-stream-markdown`）。
- **接口与要点**：
  - 助手文本用 `MessageResponse`；流式时末尾显示闪烁光标，不再降透明度。
  - 用户消息：沿用 `Message from="user"` 气泡，下方 `HH:mm`（取对应 turn 的 `created_at`，乐观占位阶段显示当前时间）与复制图标。
  - `ReplyFooter`：用 `formatTurnMeta`，`null` 时不渲染；仅在该 turn 非运行态且这条文本是该 turn 最后一个块时出现。
  - 确认 Markdown 渲染不输出原始 HTML：用含 `<script>`、`<img onerror>` 的文本写测试；若 `vue-stream-markdown` 默认不转义，就用它的选项关闭 HTML，并在「决策记录」写明。
- **测试**（先写）：助手文本里的 Markdown 表格/行内代码渲染成对应元素；`<script>` 文本不产生 script 节点（评审关注点 5）；`ReplyFooter` 在有用量/用时时显示、缺数据或运行中不显示；用户气泡显示时间；复制按钮调用剪贴板。
- **完成标准**：测试通过；`make check` 为绿。
- **验证命令**：`cd frontend && pnpm exec vitest run src/components/session`，然后 `make check`

### T10：演示脚本、L4 验收与收尾（完成，独立评审待做）

- **目标**：端到端确认真实界面效果，完成文档收尾。
- **涉及文件**：`backend/src/studio/agent/fake.py`（`default_fake_script`：用户消息等于 `/demo-activity` 时返回演示脚本，含 `think`、Read/Glob/Grep/Bash/WebSearch/WebFetch/Write 的 `emit`、一个出错的 `emit`、最后一句带 Markdown 表格的 `say`；加测试）；`docs/ARCHITECTURE.md`（session 组件结构）、`docs/glossary.md`（活动组、thinking）、`docs/quality/QUALITY.md`；删除无引用的旧组件（若 `ai-elements/tool/*` 仍被引用则保留，在 tech-debt 登记）；计划文件的「验证记录」。
- **接口与要点**：
  - 演示脚本只在 `/demo-activity` 触发，不改变其它情况下的默认回显行为（`tests/agent/test_fake.py` 加两条用例：触发与不触发）。
  - L4（由控制者在内置浏览器亲自做，不交给 subagent）：`make dev`，在 fake 运行时下发 `/demo-activity`，逐项截图——运行中的组展开、结束后自动折叠、七类工具展开样式、出错行默认展开、手动折叠后不被自动规则覆盖、刷新页面后历史回放全部折叠；再用本机 Claude 登录真实跑一轮（要求读文件 + 联网搜索 + 一条 shell），确认 thinking 与工具渲染。窗口分别用桌面与窄屏各看一次。
  - 独立评审：按 SOP §3 步骤 5 对分支跑一次 `code-review`，逐条处理。
- **测试**：fake 演示脚本用例；`make check`。
- **完成标准**：AC1–AC10 逐条有证据；计划移到 `plans/completed/`、状态改「已完成」（负责人验收后）；`make check` 全绿。
- **验证命令**：`make check`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-02 — T1 — thinking 事件贯通（events/turn_events/bus/sessions/fake），后端 agent + stream 测试 440 通过
- 2026-10-02 — T2 — Claude 运行时透传 thinking（`thinking_delta`/`ThinkingBlock` 转换，选项 `thinking=adaptive+summarized`）
- 2026-10-02 — T3 — OpenAI 运行时透传 thinking（reasoning summary delta + `ReasoningItem`；Responses 路径带 `reasoning.summary="auto"`）
- 2026-10-02 — T4 — 真实实测通过：Claude 本机登录 6 个 thinking 块、OpenAI（OpenRouter）2 个块且第二轮回放通过；ADR 0013、references、runbook 已写（风险关口通过，无需升级）
- 2026-10-02 — T5 — 前端 `ThinkingItem`、thinking 事件合并、`turns` 暴露（`useSessionStream` 31 个用例通过）
- 2026-10-02 — T6 — 四个纯函数（`groupTimeline`/`toolPresentation`/`webSearchResult`/`turnMeta`）+ 133 个会话组件用例通过
- 2026-10-02 — T7 — 活动组骨架：`SessionTimeline`/`ActivityGroup`/`ActivityRow`/`ToolPane`/`ThinkingBody`/`GenericBody`/`useDisclosure`，`SessionPanel` 已接入，旧 `ai-elements/tool` 不再被引用；会话组件 154 个用例通过
- 2026-10-02 — T8 — 七类工具专属正文（Read/Write/Glob/Grep/Bash/WebSearch/WebFetch）+ `ErrorPane`/`CodeView`/`DiffView`、`codeLanguage`/`readResult`/`isHttpUrl`；会话组件 205 个用例通过
- 2026-10-02 — T9 — 助手/思考文本渲染 Markdown 并转义原始 HTML（`markdownSafe`）、流式光标、用户气泡时间 + 复制、`ReplyFooter`（用量/用时/时间/复制）、turn 结束后刷新 turn 元数据；前端 306 个相关用例通过
- 2026-10-02 — T10 — `/demo-activity` 演示脚本；隔离数据目录下 L4 走查（运行中/自动折叠/七类工具/出错行/历史回放折叠/窄屏），修了 L4 发现的 4 个问题（见决策记录）；删除无引用的 `ai-elements/tool/*`；ARCHITECTURE/glossary/QUALITY/tech-debt（TD-44~46）/references 已更新
- 2026-10-02 — 独立评审（最强模型，全新上下文）+ 修复 — 评审 1 个 Important（Markdown 转义可被绕过）、6 个 Minor；另有 2 个没下结论的风险；已修复：转义器重写 + 渲染层拦截危险标签 + 关闭链接 favicon、`markTurnAccepted` 延迟核对、OpenAI 官方端点推理模型防护；后端 1400 个、前端 592 个用例通过

## 下一步

- 负责人验收（AC9 的「真实模型走一轮」只做了一半，见验证记录），验收后把本计划移到 `plans/completed/`、状态改「已完成」，分支合并由负责人决定。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-02 — 计划拆成「后端 → 实测 → 前端纯函数 → 组件 → L4」，且把真实模型实测（T4）放在前端工作之前 — thinking 是否真有内容决定后面是否值得做，失败就在最便宜的时候升级。
- 2026-10-02 — ccproxy 网关相关验证整体排除 — 负责人当前网络不通；Claude 侧只用本机登录验证，网关路径留待之后补测（在 QUALITY 里标「未验证」）。
- 2026-10-02 — 折叠行默认全部折叠、仅出错行展开；运行中的末尾组默认展开 — 见设计 §4.2（负责人批准计划时一并确认）。
- 2026-10-02 — T3 `model_settings`：只有 `provider=openai`（官方与网关两个分支）带 `reasoning=Reasoning(summary="auto")`，LiteLLM 路径不带（计划原文「两个分支」指这两个 openai 分支） — SDK 在 chat-completions 路径会忽略 summary 并警告；LiteLLM 路径仍会透传 provider 自己流出的 reasoning（chatcmpl 流处理器产出同名事件）；代价：LiteLLM 路径能否出现 thinking 取决于 provider，待 T4 之外的真实 DeepSeek 用例观察（不在本计划验收）。
- 2026-10-02 — 评审修复 F1（Important）：`escapeRawHtml` 能被绕过——反斜杠转义的反引号、信息串带反引号的假围栏、围栏长度不配对、关闭行带信息串，都会让转义器与 Markdown 解析器对「哪里是代码」的判断不一致，原始 `<iframe>`/`<form>`/`<meta refresh>`/带 `style` 的覆盖层渲染成真实元素（库会剥 `on*`/`javascript:`/`srcdoc`，所以没有直接执行脚本，但可以重定向、钓鱼、嵌入第三方页面）。修复：按 CommonMark 规则重写转义器并遇疑从严；新增渲染层第二层防御 `blockedHtml`（经库的 `components` 属性把危险标签换成丢弃全部属性的惰性占位）；新增 `SafeMarkdown` 统一入口；发现并关掉库默认的链接 favicon（模型一提到域名浏览器就请求 `<域名>/favicon.ico`，可编码数据外泄，`linkOptions.favicon=false`）。评审给出的全部绕过输入已写成失败测试（先 RED 后 GREEN）。
- 2026-10-02 — 评审修复 F2（重新分级为 Important）：评审把「`markTurnAccepted` 可能把面板卡在排队中」定为 Minor；按效果重新分级——卡住时输入框被禁用、只能刷新页面，而改动前这种情况只是状态为空——升为 Important。修复：发送后在 1.5 秒和 6 秒各核对一次会话详情（仍是忙碌状态才请求）。
- 2026-10-02 — 评审修复 F3：评审没下结论的「官方 OpenAI 端点对非推理模型拒绝 `reasoning`」——若成立每轮都失败，代价远大于少显示一个思考，所以官方端点只对 `^(o\d|gpt-[5-9])` 模型请求摘要（网关不变）；Claude 在 Haiku 4.5 / Sonnet 5 上的 adaptive 已实测都正常。登记 TD-47（官方端点没有真实 key 验证）。
- 2026-10-02 — 评审 Minor（延后，登记 TD-48）：原生 WebSearch 摘要正文不显示；截断的 Read 可能出现两套行号；中断后展开正文的文案；空白 delta 流式期间丢失段落分隔；多转义的嵌套围栏；`removeLocalUserMessage` 影响 key。
- 2026-10-02 — T10 L4 发现并修复的问题：① 后端时间戳是没有时区的 UTC，`formatClock` 直接 `new Date()` 在东八区差 8 小时，新增 `parseServerTime`（无时区后缀按 UTC 解析，先写失败测试）；② 思考正文被 Markdown 根节点的前景色盖掉，改 wrapper + `text-inherit!`；③ 代码块内容以换行结尾时多出一个空行号，`CodeView` 去掉末尾一个换行；④ 新建会话的首轮 `turnStatus` 为空（预存在的问题，改动前的前端同样复现），用发送接口返回的 `turn_id` 调新增的 `markTurnAccepted` 缓解（`useSessionStream` 新增导出，`SessionPanel` 的发送/继续两处调用）；根因没查清，登记 TD-44。
- 2026-10-02 — T10 演示脚本的触发判断是「提示词最后一行等于 `/demo-activity`」而不是整串相等 — `TurnRunner` 在用户消息前拼了上下文前言（L4 里第一次没触发才发现，先加失败测试再改）。
- 2026-10-02 — T10 删除 `components/ai-elements/tool/*`（生成代码，已无任何引用），并更新 `docs/references/frontend-stack.md` — 计划「不包含」里写的是「最终无引用时才删除」；需要时可用 shadcn-vue CLI 重新生成。
- 2026-10-02 — T10 L4 在隔离的数据目录（会话临时目录）和 8001/5174 端口上做，临时改了 `.claude/launch.json`（用完 `git checkout` 恢复），没有碰负责人正在运行的 8000/5173 开发实例和真实数据；另用 git worktree 起过一个改动前的前端对照实例（已删除）。
- 2026-10-02 — T9 原始 HTML 的处理：`vue-stream-markdown` 没有关闭 HTML 的选项且默认会把 `<script>` 渲染进 DOM（探针实测；内容被它拆乱所以不会按原样执行，但不能依赖），所以在交给它之前用 `escapeRawHtml` 转义代码以外的 `<`（围栏/行内代码保持原样）；助手文本和思考正文都走它；代价：Markdown 里合法的 `<https://…>` 自动链接和内联 HTML 标签都变成文本。
- 2026-10-02 — T9 turn 元数据刷新：`turn_status` 为非运行态（done/failed/cancelled/budget_exceeded/interrupted）时重新 `GET /sessions/{id}`，否则 `turns` 里新 turn 的 usage/updated_at 是 snapshot 时刻的旧值，操作栏拿不到最终用量 — 每个 turn 多一次会话详情请求；`refreshTurnStatus` 的竞态保护（`statusVersion`/`generation`）沿用。
- 2026-10-02 — T9 `UserMessageItem` 新增可选 `at`（乐观占位的发送时间），被真实 turn 认领后保留 — 真实 turn 元数据到达之前气泡下也有时间；既有 7 个 `toEqual` 用例同步加了 `at: expect.any(String)`。
- 2026-10-02 — T8 错误面板不在 `ToolBody` 统一追加，而是新增 `ErrorPane` 由各正文自己放置 — 先实现成统一追加后发现 `Write` 缺参数退回 `GenericBody` 时错误会出现两次（已加失败测试复现再重构）；`bash` 的输出本身就是结果，失败时红色显示、不另出错误面板。
- 2026-10-02 — T8 Read 结果：每行带 `行号→` 且从 1 开始连续时去掉前缀、交给代码块自己编号；起始行号不是 1（带 offset）时保留原文逐行显示（代码块行号从 1 开始，会对不上） — Claude 的 `Read` 结果实测格式；代价：带 offset 的读取没有语法高亮。
- 2026-10-02 — T8 的 WebFetch 正文用纯文本 `<pre>`，没有渲染 Markdown — 设计 §5 写的是「正文文本块」；Claude 原生 WebFetch 的结果其实是模型总结的 Markdown，显示成原文也可读；若 L4 看着太糙再改（一行改动）。
- 2026-10-02 — T7 `ThinkingBody` 用 Markdown 渲染（`MessageResponse`）而不是纯文本 — OpenAI 的 reasoning 摘要带 `**小标题**`，纯文本会把星号原样显示（T4 实测）；Claude 的思考是普通段落，Markdown 渲染无副作用。设计 §4.4 写的是「普通字体、次要色」，这里在保持次要色的前提下加了 Markdown。
- 2026-10-02 — T7 活动组里 `ToolBody` 暂时对所有种类都分发到 `GenericBody` — 专属正文是 T8；这样 T7 就能独立验收折叠行为。
- 2026-10-02 — T7 `ToolPane` 的限高用固定的 `max-h-80`（20rem），而不是「超过 40 行才限高」 — 一个类就能保证任何内容都不会撑开页面，行为上等价于设计的意图；代价：很短的内容不受影响，很长的内容在 20rem 处滚动而不是 40 行处。
- 2026-10-02 — T6 在计划外增加了两个小导出：`relativizePath`（供 `describeTool` 和组件共用）、`toolStatus(item, turnEnded)`（T7 的状态判断，纯函数放这里便于测试），并给 `ActivityGroupBlock` 加了 `key` 字段 — 都是计划 T7 本来就需要的东西，放在 T6 里一起测；代价：无。
- 2026-10-02 — T6 `describeTool`：`shell` 同时接受 `commands: string[]`（OpenAI 原生）和 `command: string`（FakeRuntime 的 shell 步骤），`list_files` 缺 `dir` 视为空（默认参数） — 两个运行时/测试替身的真实形状。
- 2026-10-02 — T5 的 `findLastStreamingIndex` 对 `text`/`thinking` 通用：同 turn 里另一种流式条目和用户消息跳过，遇到其它条目停止 — Claude 的终稿事件可能在末尾已有进行中的文本时到达 `thinking`（先 thinking 块后 text 块），旧的「只跳过用户消息」规则会造成思考条目重复；测试固定了这个顺序。
- 2026-10-02 — T5 没有加「重连回放不重复」的 composable 用例 — 重放去重在 SSE 层按 `seq` 完成（`api/sse.ts`，已有测试），composable 看不到重复；计划里这条的意图由 SSE 层测试覆盖。
- 2026-10-02 — 冒烟用例只断言「完成/有回答/收到 delta 就必须有落库块」，不断言一定有思考 — 设计是尽力透传，模型是否思考由模型决定；是否达标由人看证据判断（本次已看：两个环境都有思考）。
- 2026-10-02 — 空白 thinking 在 `turn_events.handle` 里统一丢弃（而不是各运行时各自过滤） — 运行时无关、单点保证评审关注点 1；运行时转换层仍会各自跳过明显的空串。

## 意外与发现

- 2026-10-02 — 开发环境（vite 代理）下，空会话的 SSE 响应头要等第一个事件才放出（curl 直连后端立刻有头，经 5174 没有）；新会话首轮因此错过瞬时的 `turn_status`。改动前的前端同样复现，已缓解并登记 TD-44。
- 2026-10-02 — `uvicorn --reload` 在浏览器连着 SSE 时，改文件触发的重载会卡在「Waiting for connections to close」（与 TD-22 同源），L4 期间重启了一次 API 实例。
- 2026-10-02 — `vue-stream-markdown` 默认会把 Markdown 里的原始 `<script>` 渲染成真实 DOM 元素（内容被它拆乱所以不会按原样执行），且没有关闭 HTML 的选项；因此在 `markdownSafe.escapeRawHtml` 里转义。
- 2026-10-02 — Claude 的 `thinking` 必须带 `display: "summarized"`，否则 `thinking_delta`/`ThinkingBlock` 的文本是空串；adaptive 对无关小问题（项目阶段提示下 4/4）不思考，任务型提示会在每次工具调用前思考。已写进 references 与 ADR 0013；冒烟提示因此改成任务型。
- 2026-10-02 — OpenAI 的 reasoning 摘要带 markdown 粗体小标题（如 `**Inspecting tools and files**`）。T7 的 `ThinkingBody` 展示时要能容忍（见 T7 决策）。
- 2026-10-02 — Agents SDK 的 `LitellmModel` 在 chat-completions 路径会忽略 `reasoning.summary` 并每次调用打警告（`litellm_model.py` `_get_reasoning_effort`）；因此 LiteLLM 路径不设 `reasoning`，已有测试固定。

## 阻塞

- 无

## 验证记录

后端 `make check`：1400 个测试通过（评审修复后）；前端 vitest：53 个文件、592 个用例通过（评审修复后）。证据文件在 `data/evidence/chat-ui-redesign/`（不进 git）：`smoke/`（真实模型冒烟）、`l4/`（浏览器截图）。

| AC | 证据 |
|---|---|
| AC1 | `tests/agent/test_runner.py::TestThinking`（落库/不落库/不计步/空白丢弃）、`tests/api/test_stream.py`（`WIRE_EVENT_TYPES` 共 12 种、`thinking` 回放、`thinking_delta` 无 id）、`tests/agent/test_bus.py` |
| AC2 | `tests/agent/test_claude_runtime.py::TestThinkingConversion` + `TestOptions::test_core_options`（`thinking={"type": "adaptive", "display": "summarized"}`） |
| AC3 | `tests/agent/test_openai_runtime.py::TestThinkingConversion`（含 LiteLLM 路径不设 `reasoning`） |
| AC4 | `make smoke SMOKE_ARGS="-k thinking_claude_login"`：本机 Claude 登录一轮 6 个 thinking 块、181 个 delta（任务型提示）；`-k thinking_openai`：经 OpenRouter 的 OpenAI 一轮 2 个块、281 个 delta，第二轮回放通过；证据 `smoke/*thinking*.json`；**ccproxy 网关未测**（负责人网络不通）；关于 adaptive 的实测事实写进了 references 与 ADR 0013 |
| AC5 | `groupTimeline.spec.ts`、`toolPresentation.spec.ts`（7 类 × 2 运行时表驱动 + 畸形参数）、`webSearchResult.spec.ts`、`turnMeta.spec.ts`、`codeLanguage.spec.ts`、`readResult.spec.ts` |
| AC6 | `useDisclosure.spec.ts`、`ActivityGroup.spec.ts`、`SessionTimeline.spec.ts`；L4：`l4/02-running-group-expanded.jpg`（运行中展开）→ `03-finished-collapsed-markdown-footer.jpg`（结束后自动折叠）；`01-history-replay-collapsed.jpg`（历史回放折叠）；手动展开/行展开后状态保持（`04`、`05`） |
| AC7 | `tool-bodies/toolBodies.spec.ts`（7 类 × 两个运行时、出错/截断/空结果/畸形参数/`javascript:` 链接）；L4：`05-read-expanded`、`06-glob-grep-bash`、`07-write-error-thinking`（含出错行「失败」+ 错误面板）、`08-websearch-webfetch`；「已中断」仅有单测（`ActivityGroup.spec.ts`），L4 未复现 |
| AC8 | `SessionTimelineItem.spec.ts`（Markdown 表格/行内代码、`<script>`/`<img onerror>`/事件属性不进 DOM、流式光标、用户时间/复制）、`ReplyFooter.spec.ts`、`markdownSafe.spec.ts`；L4：`03-finished-collapsed-markdown-footer.jpg` |
| AC9 | **部分**。演示脚本（`/demo-activity`，隔离数据目录，1.5 秒假延迟）完整走通：运行中/折叠/七类工具/出错行/窄屏（`l4/` 9 张）；修复首轮状态后用 DOM 采样确认「思考中…」→「运行中 · 第 N 次工具调用」+ 停止按钮。**真实模型（本机 Claude 登录）**：跑了一轮任务型提示，工具数从 2 涨到 3 时组头还是静态「N 次工具调用」（当时首轮状态缺失的预存在问题，之后已缓解），修复后没能再对真实模型截图（浏览器面板被收起，截图超时）；真实模型的 thinking/工具渲染由冒烟事件流（AC4）和演示脚本共同覆盖 |
| AC10 | ADR 0013、references（claude-agent-sdk / openai-agents-sdk / frontend-stack）、ARCHITECTURE、glossary、QUALITY、tech-debt（TD-44~46）已更新；`make check` 全绿；收尾清单（SOP §7）其余项等验收后做 |
