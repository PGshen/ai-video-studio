# chat-ui-redesign：对话页重做（活动组、工具专属渲染、thinking 事件）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
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

- [ ] AC1：`ThinkingDelta` 只发布（`thinking_delta`）、`ThinkingBlock` 落库（`thinking`）并出现在 SSE 回放；不计入步数与预算。（验证：`tests/agent/test_runner.py`、`tests/api/test_stream.py` 新增用例）
- [ ] AC2：Claude 运行时把 `thinking_delta` 流事件和 `ThinkingBlock` 转成 thinking 事件，子 agent 的 thinking 被丢弃，空文本不产生事件；`ClaudeAgentOptions.thinking` 已设置。（验证：`tests/agent/test_claude_runtime.py`）
- [ ] AC3：OpenAI 运行时把 `response.reasoning_summary_text.delta` 与 `ReasoningItem` 摘要转成 thinking 事件；`model_settings` 带 `reasoning.summary="auto"` 且不破坏既有 `store=False` / `response_include` 断言。（验证：`tests/agent/test_openai_runtime.py`）
- [ ] AC4：真实模型实测——Claude 本机登录与 OpenAI（OpenRouter）各一轮，记录是否出现 thinking 文本及内容形态；结论写入 references，证据文件在 `data/evidence/`。（验证：`make smoke` 日志）
- [ ] AC5：`groupTimeline` 按设计 §2 分组（同 turn 连续 thinking/tool_call；遇其它条目断开；末尾组标 `running`）；`toolPresentation` 对 7 类工具、两个运行时的名字与参数给出正确的种类与摘要，未知工具走 `generic`；`webSearchResult` 解析自建与 Claude 原生两种格式，失败回退原文。（验证：对应 `.spec.ts`）
- [ ] AC6：折叠规则：运行中的末尾组展开、turn 结束或后面出现文本后折叠、历史回放折叠；行默认折叠、出错行展开；用户手动状态优先且不随会话切换串线。（验证：组件测试 + L4）
- [ ] AC7：Read / Write(Edit/apply_patch) / Glob / Grep / Bash / WebSearch / WebFetch 的展开正文符合设计 §5 表格；运行中转圈、出错变红、被中断显示「已中断」。（验证：组件测试 + L4 截图）
- [ ] AC8：助手回复渲染 Markdown 且不执行模型输出里的 HTML；用户气泡下有时间与复制；回复操作栏显示复制、用量、用时、时间，数据缺失时整行不显示。（验证：组件测试 + L4 截图）
- [ ] AC9：L4——`make dev` 下用演示脚本跑一轮含 thinking 与 7 类工具的对话，并用本机 Claude 登录真实跑一轮；折叠/展开、运行中、出错行截图存证。
- [ ] AC10：ADR、references、ARCHITECTURE、glossary、QUALITY 已更新；`make check` 全绿；收尾清单（SOP §7）完成。

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

### T2：Claude 运行时透传 thinking（待开始）

- **目标**：Claude SDK 的 thinking 变成 `ThinkingDelta` / `ThinkingBlock`，并在选项里开启。
- **涉及文件**：`backend/src/studio/agent/claude_messages.py`、`agent/claude_runtime.py`（`ClaudeAgentOptions` 构造处，约 `include_partial_messages=True` 附近）；测试 `backend/tests/agent/test_claude_runtime.py`（`TestEventConversion` 与选项构造相关用例）。
- **接口与要点**：
  - `convert_message`：`StreamEvent` 的 `content_block_delta` 且 `delta.type == "thinking_delta"` → `ThinkingDelta(text=delta["thinking"])`（空串不产生）；`AssistantMessage.content` 里的 `claude_agent_sdk.ThinkingBlock` 且 `.thinking.strip()` 非空 → `events.ThinkingBlock`。`parent_tool_use_id` 非空（子 agent）整条丢弃的现有逻辑保持。
  - 选项：`thinking={"type": "adaptive", "display": "summarized"}`（SDK 0.2.160 的 `ThinkingConfigAdaptive`，见 `types.py`）。
  - `signature` 字段不外传、不落库。
- **测试**（先写）：把 `thinking_delta` 流事件、`ThinkingBlock(thinking="…", signature="s")`、空白 thinking、带 `parent_tool_use_id` 的 thinking 各构造一条消息，断言转换结果；断言构造出的 `ClaudeAgentOptions.thinking == {"type": "adaptive", "display": "summarized"}`。
- **完成标准**：测试通过；`make check` 为绿。
- **验证命令**：`cd backend && uv run pytest tests/agent/test_claude_runtime.py -q`，然后 `make check`

### T3：OpenAI 运行时透传 thinking（待开始）

- **目标**：Responses 路径与 LiteLLM 路径的 reasoning summary 变成 thinking 事件，并请求摘要。
- **涉及文件**：`backend/src/studio/agent/openai_tools.py`（`convert`）、`agent/openai_runtime.py`（`model_settings`）；测试 `backend/tests/agent/test_openai_runtime.py`。
- **接口与要点**：
  - `convert`：`RawResponsesStreamEvent` 中 `data.type == "response.reasoning_summary_text.delta"` → `ThinkingDelta(text=data.delta)`；`RunItemStreamEvent` 的 `ReasoningItem` → 从 `item.raw_item.summary[*].text` 用换行拼接，非空才产出 `ThinkingBlock`。
  - `model_settings`：两个分支都带 `reasoning=Reasoning(summary="auto")`；网关分支保留 `store=False`、`response_include=["reasoning.encrypted_content"]`。
  - 现有 `test_openai_runtime.py` 中对 `settings.response_include` 的断言（约 413–422 行）必须仍然通过；若有对整个 `ModelSettings` 做相等比较的用例，同步调整并在「决策记录」写明。
- **测试**（先写）：用 `ScriptedModel`（`ModelStep.stream([...])` 手写 reasoning 事件，参考该文件里 shell 调用的写法）驱动一轮，断言先 `ThinkingDelta` 后 `ThinkingBlock`，且之后的文本/工具事件不受影响；空摘要不产生事件；`model_settings` 两个分支都带 `reasoning`。
- **完成标准**：测试通过；`make check` 为绿。
- **验证命令**：`cd backend && uv run pytest tests/agent/test_openai_runtime.py -q`，然后 `make check`

### T4：真实模型实测、ADR 与 references（待开始）

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

### T5：前端 thinking 条目与会话状态（待开始）

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

### T6：纯函数——分组、工具归类、搜索结果解析、元信息（待开始）

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

### T7：活动组骨架与折叠（待开始）

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

### T8：七类工具的专属正文（待开始）

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

### T9：消息样式、Markdown 与元信息（待开始）

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

### T10：演示脚本、L4 验收与收尾（待开始）

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

## 下一步

- 从 T2 开始：在 `backend/tests/agent/test_claude_runtime.py` 的 `TestEventConversion` 里先写 `thinking_delta` / `ThinkingBlock` / 空白 / 子 agent 的失败测试，再改 `claude_messages.convert_message` 与 `claude_runtime.py` 的 `ClaudeAgentOptions`。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-02 — 计划拆成「后端 → 实测 → 前端纯函数 → 组件 → L4」，且把真实模型实测（T4）放在前端工作之前 — thinking 是否真有内容决定后面是否值得做，失败就在最便宜的时候升级。
- 2026-10-02 — ccproxy 网关相关验证整体排除 — 负责人当前网络不通；Claude 侧只用本机登录验证，网关路径留待之后补测（在 QUALITY 里标「未验证」）。
- 2026-10-02 — 折叠行默认全部折叠、仅出错行展开；运行中的末尾组默认展开 — 见设计 §4.2（负责人批准计划时一并确认）。
- 2026-10-02 — 空白 thinking 在 `turn_events.handle` 里统一丢弃（而不是各运行时各自过滤） — 运行时无关、单点保证评审关注点 1；运行时转换层仍会各自跳过明显的空串。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 无
