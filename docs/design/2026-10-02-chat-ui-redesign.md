# 对话页重做：活动组、工具专属渲染与 thinking 事件

状态：待负责人审阅（2026-10-02）。本文是新增设计，不修改 `2026-09-26-architecture.md`；事件协议的变化在实现时另写 ADR。

## 1. 目标与范围

把会话面板（`frontend/src/components/session/SessionPanel.vue` 及其时间线）重做成参考截图的样式：

1. 思考与工具调用整体可折叠（「活动组」）。
2. 组内每一条思考、每一个工具调用都能单独折叠。
3. 不同类型的条目样式不同：思考只有文本；工具由「请求 + 结果」组成，按工具种类专属渲染。
4. 助手回复渲染 Markdown；用户消息和回复带时间、用量、用时等元信息。
5. 后端新增 `thinking` 事件，两个 SDK 运行时都透传。

**不在范围内：** 输入框改版（沿用 `PromptInput`）；点赞/点踩、分支；设置页里的 thinking 开关；业务工具（`write_ideas`、`validate_scenes`、`render_preview` 等）的专属渲染（走通用兜底）。

## 2. 条目模型

时间线仍是扁平事件流（`useSessionStream` 的 `items`），新增一种条目：

```
ThinkingItem { kind: 'thinking', turnId, text, streaming }
```

分组在渲染层完成，不改变流的合并逻辑：纯函数 `groupTimeline(items)` 把**同一 turn 内连续的** `thinking` / `tool_call` 条目归成一个 `ActivityGroup`；遇到 `text`、`user_message`、`notice`、`error`、`snapshot`、`suggestion` 即断开。输出是 `TimelineBlock[]`：原条目，或 `{ kind: 'activity', turnId, entries, running }`。`running` 表示该组是当前运行 turn 的末尾组。

## 3. 后端：thinking 事件

沿用 `text` / `text_delta` 的双事件模式：

| 层 | 新增 |
|---|---|
| `agent/events.py` | `ThinkingDelta(text)`（只发布）、`ThinkingBlock(text)`（落库） |
| `agent/turn_events.py` | `ThinkingDelta` → `_publish("thinking_delta")`；`ThinkingBlock` → `_persist("thinking", {"text"})`。不计步数、不参与预算 |
| `agent/bus.py` | `TRANSIENT_EVENT_TYPES` 加 `thinking_delta` |
| `api/sessions.py` | `WIRE_EVENT_TYPES` 加 `thinking_delta`、`thinking` |
| 数据库 | 无迁移：`turn_events.type` 是自由字符串 |

**Claude 运行时**（`claude_messages.convert_message`）：`StreamEvent` 里 `content_block_delta` 的 `delta.type == "thinking_delta"` → `ThinkingDelta`；`AssistantMessage.content` 里的 `ThinkingBlock`（`.thinking` 非空）→ `ThinkingBlock`。`ClaudeAgentOptions` 增加 `thinking={"type": "adaptive", "display": "summarized"}`。

**OpenAI 运行时**（`openai_runtime.convert` / `model_settings`）：`response.reasoning_summary_text.delta` → `ThinkingDelta`；`RunItemStreamEvent` 的 `ReasoningItem` → 取其 `summary[].text` 拼成 `ThinkingBlock`（空则不发）。`ModelSettings` 加 `reasoning=Reasoning(summary="auto")`；LiteLLM 路径的 chat-completions 流处理器本身会产出同名的 reasoning summary 事件，一并透传。

**尽力透传，不加开关：** 模型不给推理内容就没有 thinking 条目，界面不出现「已思考」。

**需要在计划里先实测的风险（失败即按 SOP §6 升级）：**
- 本机登录的 Claude（订阅）与 ccproxy 网关下，adaptive thinking 的 `summarized` 是否真的有文本。
- OpenRouter 上的 OpenAI 系模型加 `reasoning.summary` 后，是否被网关接受、多轮回放（`store=False` + `encrypted_content`）是否仍正常。
- 结论补进 `docs/references/claude-agent-sdk.md`、`openai-agents-sdk.md`（日期 + 来源）。

## 4. 前端：活动组

### 4.1 组头

| 状态 | 文案 |
|---|---|
| 组内只有 thinking | 「已思考」（运行中：「思考中…」） |
| 组内有 ≥1 个工具 | 「N 次工具调用」（运行中：「运行中 · 第 N 次工具调用」，带转圈图标） |

右侧 chevron 表示折叠状态。

### 4.2 折叠规则

- **组：** 运行中的末尾组默认展开，便于跟随进度；所在 turn 结束或后面出现了 `text` 后自动折叠。历史回放进来的组默认折叠。
- **行（单条思考/工具）：** 默认折叠，**出错的工具行默认展开**。
- 用户手动点过的组/行，以用户的状态为准，不再被自动规则覆盖（状态按「turnId + 条目序号」存在组件内的 `Map`，不入 store）。

### 4.3 行结构

- **折叠态：** 一行 = 图标 + 类型名 + `·` + 一句摘要（见 §5 映射表）+ chevron。工具的运行状态：无结果时转圈，出错时红色，完成时不加标记。
- **展开态：** 行下方缩进显示正文（§5）。所有代码类正文用统一的 `ToolPane`：标题栏（左：标题/文件名；右：语言、「复制」）+ 内容区。

### 4.4 思考行

只有文本：折叠态显示「思考 · 首句」，展开显示全文（等宽以外的普通字体、次要色）。流式时随 `thinking_delta` 追加，结束后由 `thinking` 事件整体替换（与 `text` 一致）。

## 5. 工具专属渲染

工具名在两个运行时下不同，用一张映射表（`toolPresentation.ts`，纯函数、可单测）归一成「渲染种类」。表外的工具一律走 `generic`。

| 渲染种类 | 工具名（Claude 原生 / OpenAI·自建） | 折叠摘要 | 展开正文 |
|---|---|---|---|
| `read` | `Read` / `read_file` | 「读取 · 文件相对路径」 | 请求：路径（+ offset/limit）；结果：代码块，标题栏是文件名、语言按扩展名推断（`shiki`），内容带行号（Claude 的 `Read` 结果本身带行号，自建工具的结果由前端补）；被截断（`truncated`）时末尾提示「已截断」 |
| `write` | `Write` / `write_file`；`Edit`、`MultiEdit` / `edit_file`；`apply_patch` | 「写入 / 编辑 / 补丁 · 路径」 | `Write`：请求中的 `content` 代码块；`Edit`：`old → new` 差异块；`apply_patch`：`diff` 文本；结果只显示一行状态文字 |
| `glob` | `Glob` / `list_files` | 「Glob · pattern」/「列目录 · dir」 | 结果按行显示为文件列表 |
| `grep` | `Grep`（无自建对应） | 「Grep · pattern」 | 结果文本块（等宽，保留换行） |
| `bash` | `Bash` / `shell` | 摘要取 `description`，没有就取命令第一行 | 终端风格块：状态点 + 命令（`shell` 的 `commands` 逐条列出）+ 输出；标题栏右侧「复制」。状态点：运行中转圈、成功绿、失败红 |
| `web-search` | `WebSearch` / `web_search`（自建与 OpenAI 托管同名） | 「联网搜索 · query」 | 把结果解析成条目卡片（标题、链接、发布时间、摘要）；解析规则覆盖自建工具的编号文本和 Claude 原生的 `Links: [...]` JSON，**解析失败回退为原始文本块** |
| `web-fetch` | `WebFetch` / `fetch_url` | 「读取网页 · 域名 + 路径」 | 请求：可点击的 URL（新标签页，`rel=noopener`）；结果：正文文本块（自建工具结果开头的「外部内容」提示行原样保留） |
| `generic` | 其余（含业务工具） | 「工具名 · 第一个字符串参数」 | 参数 JSON + 结果文本 + 结果图片缩略图（沿用现有 `blobUrl` 逻辑） |

通用规则：路径一律显示工作区相对路径（去掉工作区绝对前缀）；结果为空时显示「（无输出）」；结果过长（> 40 行）时内容区限高并可滚动，不整体撑开页面。

## 6. 消息与元信息

- **助手文本：** 用 `MessageResponse`（`vue-stream-markdown`，已在依赖里）渲染；流式中不再降低透明度，改为末尾光标闪烁。
- **用户消息：** 右侧气泡（沿用 `Message` 的 `is-user` 样式），气泡下方显示时间 `HH:mm` 和「复制」图标。
- **回复操作栏：** 每个 turn 最后一条助手文本下方一行：复制、「用量 51K tok」、「用时 6 秒」、时间。数据来自 `GET /sessions/{id}` 的 `TurnOut`（`usage` 的 input+output token、`updated_at − created_at`、`created_at`），不需要后端新字段；turn 未结束或数据缺失时整行不显示。`useSessionStream` 需要对外暴露 `turns`（已有 `knownTurns`，改为响应式 `Map` 暴露）。
- 保留现有的 `notice` / `error` / `snapshot` / `suggestion` 样式逻辑，只统一圆角和间距。

## 7. 文件结构

```
frontend/src/components/session/
  SessionPanel.vue            # 只保留布局和输入区
  SessionTimeline.vue         # 新：遍历 TimelineBlock
  SessionTimelineItem.vue     # 瘦身：用户/助手/notice/error 等简单条目
  activity/
    ActivityGroup.vue         # 组：组头 + 行列表
    ActivityRow.vue           # 行：折叠头 + 展开槽
    ThinkingBody.vue
    tool-bodies/{Read,Write,Glob,Grep,Bash,WebSearch,WebFetch,Generic}Body.vue
    ToolPane.vue              # 标题栏 + 复制 + 内容区
  groupTimeline.ts            # 纯函数 + spec
  toolPresentation.ts         # 工具名/参数/结果 → 渲染种类、摘要；纯函数 + spec
  webSearchResult.ts          # 搜索结果解析；纯函数 + spec
  turnMeta.ts                 # 用量/用时/时间格式化；纯函数 + spec
```

`ai-elements/tool/*` 保持不动（生成代码），新组件不再依赖它；旧组件若最终无引用，在收尾时删除并记入 tech-debt。沿用项目分层规则（`eslint.config.ts` 的 `no-restricted-imports`），单个 `.vue` 文件控制在约 250 行内。

## 8. 错误与边界

- `tool_result` 先于 `tool_call` 到达的情况不存在（现有流已按 `call_id` 配对）；组内出现没有结果的工具且 turn 已结束（被取消/崩溃）→ 行显示「已中断」而不是一直转圈。
- 参数形状异常（缺 `file_path`、`command` 等）→ 摘要退回工具名，正文走 `generic`。
- `thinking` 文本为空不产生条目；仅含空白的 delta 忽略。
- Markdown 渲染来自模型输出，不允许原始 HTML（沿用 `vue-stream-markdown` 默认的转义行为，实现时用测试确认）。

## 9. 测试与验证

**后端（先写失败测试）：**
- `events`/`turn_events`：`ThinkingBlock` 落库、`ThinkingDelta` 只发布不落库、不增加步数。
- `claude_messages`：`thinking_delta` 与 `ThinkingBlock` 的转换（含子 agent 流量丢弃）。
- `openai_tools`/`openai_runtime`：reasoning summary delta 与 `ReasoningItem` 的转换；`model_settings` 带 `reasoning`。
- `sessions` SSE：`thinking` 会回放，`thinking_delta` 不回放。
- `make smoke`：Claude 本机登录、OpenAI（OpenRouter）各跑一轮，确认实际出现 thinking 并写入 references。

**前端（vitest，纯函数为主）：** `groupTimeline`（断开规则、running 标记）、`toolPresentation`（每种工具两种运行时的名字与参数 → 种类/摘要）、`webSearchResult`（两种格式 + 回退）、`turnMeta`、`useSessionStream` 对 `thinking_delta`/`thinking` 的合并。

**L4：** 用 `make dev` + 内置浏览器，在 fake runtime 下跑一轮包含 thinking、Read、Write、Glob、Grep、Bash、WebSearch、WebFetch 的脚本化对话，截图核对折叠/展开、出错行、运行中状态；再用真实模型走一轮（优先本机登录）。`make check` 必须全绿。

## 10. 文档与决策

- 新 ADR：事件协议新增 `thinking` / `thinking_delta`，以及「尽力透传、不加开关」的取舍。
- 更新 `docs/references/`（SDK 实测）、`docs/ARCHITECTURE.md`（前端 session 组件结构）、`docs/glossary.md`（活动组）。
- 计划放 `docs/plans/active/`，建议拆成三段：A 后端 thinking（含冒烟实测）→ B 前端纯函数与活动组骨架 → C 工具专属渲染与元信息、L4 验收。
