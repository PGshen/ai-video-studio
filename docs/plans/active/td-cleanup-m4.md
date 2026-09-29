# M4 后技术债清理（TD-19 / TD-25 / TD-27 / TD-38 / TD-39 / TD-40）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 进行中 |
| 里程碑 | M4 与 M5 之间（整理） |
| 设计依据 | [架构设计 §4.4、§5.1](../../design/2026-09-26-architecture.md)；ADR [0009](../../decisions/0009-Shell沙箱.md)、[0010](../../decisions/0010-联网模式开关.md)；登记表 [tech-debt.md](../../quality/tech-debt.md) |
| 分支 | `td-cleanup-m4` |
| 批准记录 | 2026-09-29：负责人要求"M5 之前先处理技术债"，并批准按建议范围执行（TD-19、TD-40、TD-25 预算部分、TD-27 低成本部分、TD-39 中不花钱的一半） |

## 目标

M5（设置页、风格库、回退建议）开始之前，处理掉会被 M5 放大的几条债：设置页会暴露联网模式开关和预算（TD-39、TD-25），TD-19 登记时就指定 M5 处理；顺带处理两条小债（TD-40、TD-27 的低成本部分）。完成后 `make check` 为绿。

## 范围

**包含：**
- TD-19：重启后从未开始的 turn，[继续] 改为重发原消息。
- TD-25 的预算误判部分：含上一轮残余的 `Usage` 不参与成本预算判断，并提示用户。
- TD-27 的低成本部分：两条沙箱路径追加拒读 `~/.ssh`、`~/.aws` 等。
- TD-39 的 Claude 侧：`native` 模式给 `WebFetch` 加 `PreToolUse` hook，套用与自建 `fetch_url` 相同的「URL 来源」规则；搜索结果 URL 从 `WebSearch` 的 `PostToolUse` 结果里收集。
- TD-38（顺带）：进程内的「搜索过的 URL」集合改为有上限的 LRU（TD-39 的 hook 要共用这份集合，所以一并处理）。
- TD-40：头脑风暴抽屉收起后保持挂载。

**不包含：**
- TD-25 的首轮孤儿账目；TD-26。
- TD-27 的 `~/.claude/projects` 拒读（需要真机验证，风险见登记表）。
- TD-39 的 OpenAI 托管 `WebSearchTool` 经 OpenRouter 的验证（产生 API 费用，SOP §6 第 7 条，需负责人另行同意）。
- 设置页里的联网模式风险提示（属于 M5 设置页任务）。
- TD-9、TD-14、TD-22、TD-23、TD-24。

## 任务

### T1 TD-40：抽屉收起后保持挂载
- `pages/IdeasPage.vue`：第一次打开后用 `v-show` 保持 `BrainstormDrawer` 挂载（从没打开过时不挂载，避免页面一加载就创建会话请求）；收起时网格恢复单列。
- L4：打开抽屉发一条让 agent 建卡片的消息，立刻收起，卡片仍实时出现在网格里。

### T2 TD-25：含残余的花费不判预算
- `agent/turn_events.py::handle`：`Usage.includes_carryover` 为真时跳过 `max_cost_per_turn` 判断（残余金额无法从累计差值里分离，宁可漏判也不误判）；首次遇到时落一条 `notice`（`kind: "cost_carryover"`）。
- `agent/turn_state.py::_State` 记录是否含残余，`turn_finish.py` 写入 turn 的 `usage`（`includes_carryover`）。
- 前端 `SessionTimelineItem.vue` 的 notice 文案表加 `cost_carryover`；`types/events.ts` 注释更新。
- 测试：含残余的 `Usage` 超过预算不触发 `budget_exceeded`，但落 notice；不含残余仍触发。

### T3 TD-19：重启后重发原消息
- `db/repo/turns.py`：新增 `turn_has_events(engine, turn_id)`。
- `api/sessions.py::continue_session_endpoint`：最近一个 turn 是 `interrupted` 且没有任何持久事件（从未真正开始）时，发送该 turn 的 `user_message`，否则仍发"继续"。
- `api/schemas.py::TurnOut` 新增 `never_started: bool`（仅对 `interrupted` 的 turn 计算，其余为 `false`）；`GET /sessions/{id}` 返回。
- 前端：`types/api.ts`、`useSessionStream.ts` 的 `TurnStatusState` 带上 `neverStarted`/`userMessage`（SSE 收到 `interrupted` 时重新拉一次会话）；`turnControls.ts` 给出按钮文案（"继续"/"重新发送"）；`SessionPanel.vue` 的乐观占位用原消息文本。
- 测试：后端（队列中的 turn 经 `recover_on_startup` 后 `continue` 得到原消息；已跑过的 turn 仍发"继续"）；前端纯逻辑。

### T4 TD-27：追加拒读敏感主目录
- 新增 `agent/sandbox_paths.py::sensitive_home_dirs(home)`：`~/.ssh`、`~/.aws`、`~/.gnupg`、`~/.kube`、`~/.docker`、`~/Library/Keychains`。
- `claude_scope.sandbox_settings` 与 `openai_runtime` 的 `_shell_deny_read` 都追加这份列表。
- 测试：两个配置里都含这些路径；Seatbelt 真机实测读 `~/.ssh` 被拒（有 `sandbox-exec` 时的慢测试或 L4 命令）。
- 真实 Claude 登录冒烟确认 Bash 与登录本身不受影响。

### T5 TD-39 + TD-38：`native` 模式的 WebFetch URL 来源
- 新增 `agent/url_source.py`：从 `stages/common/web_tools.py` 搬出 `normalize_url`、`refusal_reason`、`urls_in` 和「搜索过的 URL」集合（改为最多保留 N 个会话的 LRU，TD-38）；`web_tools.py` 改为从这里导入，行为不变。
- `agent/claude_scope.py`：新增 `web_fetch_hook`（`PreToolUse`，matcher `WebFetch`）和 `web_search_collect_hook`（`PostToolUse`，matcher `WebSearch`，对序列化后的 `tool_response` 用 `urls_in` 提取 URL 记入集合，不依赖返回结构）。
- `agent/claude_runtime.py::_options`：`ctx.allow_web` 时注册这两个 hook。
- 测试：搜索过/用户贴过的 URL 放行，凭空构造的、IP 字面量、内网域名拒绝；LRU 淘汰；`web_tools` 现有测试不变。
- 真实 Claude 登录冒烟：`make smoke SMOKE_ARGS="-k native"`（免费），确认 `WebSearch` 结果里的 URL 能被收集、`WebFetch` 被放行/拒绝的行为符合预期，并把 `tool_response` 的实际形状写进 `docs/references/claude-agent-sdk.md`。

### T6 收尾
- tech-debt.md：TD-19、TD-38、TD-40 移到已处理；TD-25、TD-27、TD-39 改写剩余部分。
- QUALITY.md 相关模块同步；references 补充；ADR 0010 更新「影响」；计划归档到 `completed/`。

## 验收标准

- [ ] AC1 TD-40：抽屉收起后新建的卡片仍实时出现
- [ ] AC2 TD-25：含残余的成本不会触发 `budget_exceeded`，界面有提示
- [ ] AC3 TD-19：重启后排队中的消息，[重新发送] 发出的是原消息
- [ ] AC4 TD-27：两条路径的沙箱都拒读 `~/.ssh` 等；真实 Claude 登录冒烟不受影响
- [ ] AC5 TD-39/TD-38：`native` 模式下 `WebFetch` 只能抓搜索过或用户贴过的 URL，冒烟验证过
- [ ] AC6 tech-debt.md 与 QUALITY.md 已更新，`make check` 为绿

## 验证命令

- `make check`
- `make smoke SMOKE_ARGS="-k claude_login"`（T4、T5，登录订阅，不产生 API 费用）
- L4：浏览器验证 AC1、AC3

## 进度

- [ ] T1（TD-40）
- [ ] T2（TD-25）
- [ ] T3（TD-19）
- [ ] T4（TD-27）
- [ ] T5（TD-39、TD-38）
- [ ] T6（收尾）

## 下一步

从 T1 开始，顺序执行。基线（2026-09-29，分支创建时）`make check` 全部通过。

## 决策记录

- 2026-09-29：TD-19 用「没有任何持久事件」判断「从未开始」，不加数据库列，也不依赖 `start_snapshot_id`（无项目的头脑风暴 turn 运行中也没有起始快照）。
- 2026-09-29：TD-25 只做「不误判」。残余金额无法从累计差值里分离，所以含残余的 `Usage` 整体不参与判断；漏判只会发生在 API key 模式下两次连续强制取消的极端场景，且 Claude 自己的 `max_budget_usd` 仍生效。

## 意外与发现

无。

## 阻塞

无。

## 验证记录

（执行中填写）
