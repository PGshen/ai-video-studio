# model-connectivity-test：模型配置的连通性测试

<!-- 只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 待验收 |
| 里程碑 | 零散需求（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | 负责人 2026-10-10 在对话中提出"模型配置，支持测试连通性"；沿用 [架构设计](../../design/2026-09-26-architecture.md) 的运行时分层，不需要新设计 |
| 分支 | `model-connectivity-test` |
| 批准记录 | 2026-10-10：负责人批准计划；测试入口只放在列表行上；会话内直接执行 |

## 目标

在设置页「模型配置」里，每一行可以点「测试」：后端用这个配置真的发一次极小的请求，界面显示成功（耗时、模型的回复）或失败（简短原因，例如密钥没配、401、超时、模型名不存在）。改完一个配置后不用新建会话就能确认它能用。

## 范围

**包含：**

- 后端：把会话自动命名里的"单轮、无工具调用"抽成共用函数 `agent/oneshot.py`，命名和连通性测试都用它。
- 后端：`POST /api/model-profiles/{id}/test`，按配置的运行时分派（`claude`：Agent SDK `query()`；`openai`：Agents SDK `Runner.run`；`fake`：直接成功）。
- 前端：列表每行加「测试」按钮，行内显示结果；测试中按钮转圈、可同时测多行。
- 文档：`docs/references/`（Claude SDK 失败时的消息形态，如实测到新行为）、QUALITY.md。

**不包含：**

- 编辑对话框里"未保存就测试"（要把一份未保存的配置传给后端，接口更复杂；需要的话下一步再加）。
- 自动定时探测、把测试结果存进数据库。
- 测试请求的花费计入任何会话（用量极小，与自动命名一致，不计）。

## 全局约束

- 不引入新依赖；不改现有接口的形状，只新增一个端点。
- 响应里**永远不出现 key 的值**；错误信息截断到 300 字，并把配置里的 base_url 账号密码打码（复用 `_mask_base_url`）。
- 密钥未配置（`key_configured=false`）时不发请求，直接返回失败和原因。
- 超时 30 秒；超时算失败。
- 测试请求：系统提示要求只回 `ok`，`max_turns=1`，无工具、关闭思考，尽量便宜。

## 接口

```
POST /api/model-profiles/{id}/test   → 200
{ "ok": bool, "latency_ms": int | null, "reply": str | null, "error": str | null }
```

配置不存在 → 404。运行时未启用（例如 Fake 关闭时测 `fake`）→ 200、`ok=false`、`error` 说明原因。

## 验收标准

- [x] AC1：`fake`、密钥未配置、超时、SDK 抛错、模型返回空文本、Claude 返回 `is_error` 的 result 这几种情况都有单元/接口测试，返回值符合上面的约定；任何情况下响应里都不含 key 的值。（验证：`make check`）
- [x] AC2：会话自动命名的行为不变（`test_titler.py` 原样通过）。
- [x] AC3：本机用 `claude-login` 点「测试」成功，显示耗时和回复；把一个配置的 `model` 改成不存在的名字，点「测试」显示失败原因。（验证：浏览器截图；用本机登录，不产生 API 费用）
- [x] AC4：`make check` 全绿。

## 任务

### T1：抽出单轮调用 `agent/oneshot.py`（完成）

- **目标**：`ask_once(profile, system, message, *, data_dir, environ, timeout) -> str`，失败时抛出带简短原因的异常；Claude 分支除了收集文本，还要识别 `ResultMessage.is_error`/`AssistantMessage.error` 并抛出。titler 改为调用它，行为不变。
- **涉及文件**：`backend/src/studio/agent/oneshot.py`（新）、`agent/titler.py`、`backend/tests/agent/test_oneshot.py`（新）。
- **测试**：替身 `query`/`Runner.run` 下的成功、空文本、`is_error`、未知运行时；`test_titler.py` 不改。

### T2：连通性测试端点（完成）

- **目标**：`agent/probe.py` 的 `probe_profile(...) -> ProbeResult`（计时、超时、错误规整与打码）+ `api/profiles.py` 新端点 + `schemas.py` 的 `ModelProfileTestOut`。probe 函数通过依赖注入，接口测试用替身。
- **涉及文件**：`agent/probe.py`（新）、`api/profiles.py`、`api/schemas.py`、`api/deps.py`、`main.py`、`backend/tests/agent/test_probe.py`、`backend/tests/api/test_profiles.py`。
- **测试**：AC1 列出的各情况；404；错误文本里的 key、base_url 账号密码被去掉。

### T3：前端「测试」按钮与结果展示（完成）

- **目标**：类型（`types/api`）、`testModelProfile`（见决策记录：不用 mutation）、`ModelProfilesPanel.vue` 每行「测试」按钮；结果显示在该行名称下方：成功"✓ 1.2s · ok"，失败红字原因；按行独立维护状态。
- **涉及文件**：`frontend/src/types/api.ts`、`frontend/src/api/*`、`frontend/src/features/settings/ModelProfilesPanel.vue`、`settingsView.ts`（结果格式化纯函数）及其 spec。
- **测试**：`settingsView.spec.ts` 覆盖格式化；组件测试覆盖点击 → 转圈 → 显示结果。

### T4：实测与收尾（完成）

- `make dev` + 浏览器按 AC3 实测并截图；把新发现的 SDK 行为写进 references；更新 QUALITY.md；填「验证记录」。

## 进度

- 2026-10-10 — T1 — `ask_once` 抽出，titler 改用它，`test_titler.py` 原样通过（dbad7f5）
- 2026-10-10 — T2 — `agent/probe.py` + `POST /api/model-profiles/{id}/test`，`app.state.probe` 注入（f8cec87）
- 2026-10-10 — T3 — 列表每行「测试」按钮，结果显示在名称下方（ca90104）
- 2026-10-10 — T4 — 本机实测四种结果并截图；references、QUALITY 已更新（0e7fb1e）
- 2026-10-10 — 评审 — 1 条 Important（生成器未关闭）已修，Minor 已记录（de984c4 提交时 pyright 未过，下一个 commit 补上 `cast` 后 `make check` 全绿）

## 下一步

- 评审已完成并处理。请负责人验收，按 SOP §7 收尾（计划移到 `completed/`、rebase 到 main、`make check`、`--no-ff` 合并）。

## 决策记录

- 2026-10-10 — 前端不用 vue-query 的 mutation，面板里按配置 id 记一个 `reactive` 状态表，直接调 `testModelProfile` — 一个 mutation 只有一份 pending/结果，做不到各行独立、同时测；测试结果也不需要进缓存。
- 2026-10-10 — 运行时未启用（`runtimes.has` 为假）时端点返回 200、`ok=false`，不发请求 — 和其它失败一样在行内显示，不弹错误。
- 2026-10-10 — 错误打码在 `agent/probe.py` 里自己做（去掉密钥值、base_url 的账号与密码，前后各试一次 URL 解码），不复用 `api/profiles._mask_base_url` — agent 层不能 import api。
- 2026-10-10 — 用真实的最小请求而不是只查 `/models` 之类的接口 — 只有真实请求能同时验证 base_url、密钥、模型名和运行时（尤其 Claude 走 CLI）这一整条链路。

## 意外与发现

- 2026-10-10 — 独立评审：`oneshot._claude` 在 `async for` 里提前 raise 时 `query()` 生成器不会被关闭（SDK `_internal/client.py` 注释也写明），CLI 子进程要等 GC 才收尾；改为 `contextlib.aclosing`，补测试 `test_claude_stream_is_closed_when_raising_early`。
- 2026-10-10 — 评审备注：AC2「命名行为不变」严格说有一处变化——以前助手消息带 `error` 时错误正文会被当成标题，现在抛错、titler 返回 `None`（保留截取的临时标题），属于改进。
- 2026-10-10 — Claude CLI 对不存在的模型返回 `AssistantMessage.error="model_not_found"`，不在 SDK 的 `AssistantMessageError` 类型里；`oneshot` 只把它当字符串拼进原因，不受影响。已写进 references/claude-agent-sdk.md。
- 2026-10-10 — 本机登录的单轮极小请求约 12–14 秒（主要是 CLI 启动），所以超时设 30 秒；界面上测试中按钮显示「测试中…」。

## 阻塞

- 无

## 验证记录

- AC1、AC2、AC4：`make check` 全绿（T1–T3 每次提交前各跑一次；后端新增 `tests/agent/test_oneshot.py` 5 个、`test_probe.py` 9 个、`tests/api/test_profiles.py::TestProbe` 4 个；前端 `ModelProfilesPanel.spec.ts` 2 个、`probeSummary` 4 个、endpoints 1 个；`test_titler.py` 未改动并通过）。
- AC3：在 worktree 上用 8010/5183 端口另起 api（开 Fake，未加载 `backend/.env`）和前端，设置页逐行点「测试」，结果：
  - `fake` → `连通 · fake 运行时不发请求`
  - `claude-sonnet`（进程里没有 `ANTHROPIC_API_KEY`）→ `失败 · 环境变量 ANTHROPIC_API_KEY 未设置（写在 backend/.env 后重启）`，未发请求
  - `claude-login` → `连通 · 13.9s · ok`
  - 临时新建的 `broken-login`（本机登录，`model=claude-no-such-model`）→ `失败 · 11.9s · model_not_found: There's an issue with the selected model (claude-no-such-model). …`；验证完已删除
  - 截图见本会话（内置浏览器）；`gpt`、`deepseek` 走付费 key，未实测。
