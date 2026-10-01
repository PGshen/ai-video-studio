# 0013：新增 thinking 事件，尽力透传、不加开关

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳 |
| 日期 | 2026-10-02 |
| 相关 | [对话页重做设计](../design/2026-10-02-chat-ui-redesign.md)、[计划 T1–T4](../plans/active/chat-ui-redesign.md)、[架构设计 §3.1、§4.1](../design/2026-09-26-architecture.md)、[claude-agent-sdk.md](../references/claude-agent-sdk.md)、[openai-agents-sdk.md](../references/openai-agents-sdk.md) |

## 背景

对话页重做要把「思考」和「工具调用」一起放进可折叠的活动组。原有事件协议里没有思考内容：两个运行时都没有透传推理文本，也没有开启推理输出。

约束：Claude 与 OpenAI 两个运行时形态不同；`text`/`text_delta` 已经有「瞬时增量 + 落库整块」的成熟做法；模型是否思考由模型自己决定（实测见 references）。

## 决定

1. **两个新事件，和 `text` 一致**：`thinking_delta`（瞬时，只发布、不落库、SSE 帧无 `id`）与 `thinking`（落库、可回放、`payload = {text}`）。运行时事件 `ThinkingDelta` / `ThinkingBlock`；`turn_events.type` 是自由字符串，无需迁移。
2. **运行时无关的过滤放在 `TurnRunner` 事件处理里**：空白文本一律丢弃；thinking 不计步数、不参与预算。
3. **尽力透传，不加设置页开关**：Claude 设 `thinking={"type": "adaptive", "display": "summarized"}`（必须 `summarized`，否则文本为空）；OpenAI 在 `provider=openai` 路径设 `reasoning=Reasoning(summary="auto")`；LiteLLM 路径不设（SDK 会忽略并警告），provider 自己流出的 reasoning 仍会透传。模型这轮没有思考时，界面就没有「已思考」。
4. `signature` 与加密 reasoning 内容只用于模型自己的会话回放，不对外透传、不落库到事件里。

## 考虑过的其他方案

- **per-profile 的 thinking 开关**：要加配置字段、设置页和迁移；而是否思考本来就由模型（adaptive）决定，开关的收益很小。不选的原因：范围和维护成本超过价值，需要时再加。
- **前端不展示思考**：改动最小，但达不到参考截图的结构，且丢掉了「为什么调这个工具」的上下文。
- **思考作为 `text` 事件的一个字段**：会让所有消费 `text` 的地方（回放、落库、时间线合并）都要区分，不如独立事件清晰。

## 影响

- SSE 协议新增两个事件名（`WIRE_EVENT_TYPES` 共 12 种）；旧前端会忽略未知事件，不受影响。
- 落库多了 `thinking` 行，`turn_events` 体积略增；`tool_result` 的 8000 字截断规则不适用于 thinking（单块通常几百到一两千字符）。
- 模型是否出现 thinking 取决于模型与提示：与任务无关的小问题经常没有（实测 4/4），需要规划的任务型提示会在每次工具调用前出现。验收和演示要用任务型提示。
- OpenAI 的摘要带 markdown 小标题，前端展示时要能容忍。
- OpenAI 官方端点（`api.openai.com`）对非推理模型会拒绝 `reasoning` 参数，那样每一轮都会失败；所以官方端点只对名字像推理模型的（`o*`、`gpt-5`~`gpt-9*`）请求摘要，网关（如 OpenRouter）沿用「总是请求」（已实测接受）。官方端点的这条路径没有用真实 key 验证（TD-47）。
- 渲染模型输出的 Markdown 是不可信输入：原始 HTML 在源文本里转义（遇疑从严）+ 渲染层拦截危险标签 + 关掉链接 favicon（否则模型一提到域名浏览器就去请求它，可被用来外泄数据），见计划 T9 与评审修复记录。
