# OpenAI Agents SDK（Python，`openai-agents`）

用于 `agent/` 中的 OpenAIRuntime。

**安装版本（T10，2026-09-27）**：`openai-agents 0.22.3`（`openai-agents[litellm]`，依赖范围 `>=0.22.3,<0.23`），随之安装 `openai 3.19.2`、`litellm 1.83.0`。旧项目锁定的是 `0.22.0`。下文"源码"指 `backend/.venv/lib/python3.12/site-packages/agents/` 下的文件。

## 事实

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-09-26） | 托管工具（`WebSearchTool`、`FileSearchTool`、`CodeInterpreterTool`、`ImageGenerationTool`、`HostedMCPTool` 等）**只能**配合 Responses API（`OpenAIResponsesModel`）使用，不兼容 Chat Completions 和 LiteLLM | [官方 Tools 文档](https://openai.github.io/openai-agents-python/tools/) |
| ✅ 已验证（2026-09-26） | 本地执行的工具有：`ShellTool`（需要提供 executor，也支持托管容器）、`ApplyPatchTool`（需要实现 `ApplyPatchEditor`）、`ComputerTool`、`LocalShellTool`（旧版） | 同上 |
| ⚠️ T15 实测 | 官方文档称本地工具"适用于任何模型后端"，但 `shell`/`apply_patch` 依赖模型经过相应训练；通过 LiteLLM 接入的 DeepSeek、豆包能否正确使用未知（R1）。M1 的 LiteLLM 路径默认用兜底文件工具、不给 Shell | 同上 |
| ✅ 已验证（2026-09-27） | `ApplyPatchEditor` 是 Protocol：`create_file`/`update_file`/`delete_file(operation: ApplyPatchOperation)`，返回 `ApplyPatchResult \| str \| None`（可以是 awaitable）。`ApplyPatchOperation` 字段：`type`（`create_file`/`update_file`/`delete_file`）、`path`、`diff`（V4A 格式，删除时为空）、`move_to`、`ctx_wrapper`。`ApplyPatchResult(status="failed")` 让 `apply_patch_call_output.status` 为 `failed`；editor 抛异常也会变成失败结果，但 SDK 会额外记一条错误日志 | 源码 `editor.py`、`run_internal/tool_actions.py`（`ApplyPatchAction`） |
| ✅ 已验证（2026-09-27） | SDK 自带 `agents.apply_diff(input, diff, mode="default"\|"create")` 把 V4A diff 应用到文本上，上下文不匹配时抛 `ValueError`。SDK 的沙箱实现（`sandbox/apply_patch.py`）就是这样写的：create 用 `mode="create"` 覆盖写入，update 支持 `move_to`（写新路径再删旧路径），delete 要求文件存在 | 源码 `apply_diff.py`、`sandbox/apply_patch.py` |
| ✅ 已验证（2026-09-27） | `ShellTool(executor=...)`：`environment` 缺省为 local，local 模式**必须**提供 executor。executor 签名 `(ShellCommandRequest) -> str \| ShellResult`（可 awaitable）；`request.data` 是 `ShellCallData(call_id, action=ShellActionRequest(commands: list[str], timeout_ms, max_output_length))`。返回 `ShellResult(output=[ShellCommandOutput(stdout, stderr, outcome=ShellCallOutcome(type="exit"\|"timeout", exit_code), command)])`；SDK 按 `max_output_length` 截断并渲染成 `$ cmd\n<输出>\nexit code: N` 文本回给模型。executor 抛异常 → `status="failed"` | 源码 `tool.py`、`run_internal/tool_actions.py`（`ShellAction`） |
| ✅ 已验证（2026-09-27） | `FunctionTool(name, description, params_json_schema, on_invoke_tool, strict_json_schema=True)`：`on_invoke_tool(ToolContext, args_json: str)`，`ToolContext.tool_call_id` 可用。`strict_json_schema=True` 时构造阶段调用 `ensure_strict_json_schema`：自动加 `additionalProperties: false`、把全部属性列为 required；无法转成 strict 的 schema（开放 dict 等）抛 `UserError` | 源码 `tool.py`、`strict_schema.py` |
| ⚠️ T15 实测 | strict 模式下 Pydantic 字段默认值会留在 schema 里（例如 `"default": ""`），OpenAI 是否接受 | 源码观察 |
| ✅ 已验证（2026-09-27） | 函数工具返回 `[ToolOutputText(text=...), ToolOutputImage(image_url="data:image/png;base64,...")]` 时，`function_call_output.output` 变成 `[{"type": "input_text", ...}, {"type": "input_image", "image_url": ...}]` 发给下一次模型调用；`ToolCallOutputItem.output` 是原始返回值 | 源码 `tool.py`；T10 用 `ScriptedModel` 实测 |
| ⚠️ T15 实测 | 非 OpenAI 模型（LiteLLM 路径）收到图片工具输出时的表现（R2） | — |
| ✅ 已验证（2026-09-27） | `SQLiteSession(session_id, db_path, ..., session_settings=None)`：同一 `db_path` 可存多个会话。`SessionSettings(limit)` 只按**条目数**截取；按轮次裁剪要用 `RunConfig.session_input_callback(history, new_items) -> list`——SDK 只持久化属于本轮的新条目，回调裁剪的只是发给模型的输入 | 源码 `memory/sqlite_session.py`、`memory/session_settings.py`、`run_internal/session_persistence.py`（`prepare_input_with_session`） |
| ✅ 已验证（2026-09-27） | `LitellmModel(model, base_url=None, api_key=None)`：`api_key`/`base_url` 显式传给 `litellm.acompletion`，不需要改 `os.environ`。位于 `agents.extensions.models.litellm_model`，import 时会加载 litellm（耗时数秒），本项目延迟到 LiteLLM 路径才 import | 源码 `extensions/models/litellm_model.py` |
| ✅ 已验证（2026-09-27） | `OpenAIResponsesModel(model, openai_client: AsyncOpenAI)`；`AsyncOpenAI(api_key=..., base_url=...)` 显式构造即可，不读环境变量 | 源码 `models/openai_responses.py` |
| ✅ 已验证（2026-09-27） | `RunHooks.on_llm_end(context, agent, response: ModelResponse)` 每次模型调用后触发，`response.usage` 是**这一次**调用的 `Usage(requests, input_tokens, output_tokens, input_tokens_details.cached_tokens, ...)`；`context.usage`/`result.context_wrapper.usage` 是本次运行的累计值 | 源码 `lifecycle.py`、`usage.py`；`ScriptedModel` 实测 |
| ✅ 已验证（2026-09-27） | `Runner.run_streamed(...).stream_events()` 产出三类事件：`RawResponsesStreamEvent`（`data.type == "response.output_text.delta"` 时 `data.delta` 是文本增量）、`RunItemStreamEvent`（`name` 为 `message_output_created`/`tool_called`/`tool_output` 等，`item` 是 `MessageOutputItem`/`ToolCallItem`/`ToolCallOutputItem`）、`AgentUpdatedStreamEvent`。`tool_called` 在整个模型响应结束后才发出。`ToolCallItem.raw_item` 按类型不同：`function_call` 是 `ResponseFunctionToolCall`（`name`、`arguments` JSON 字符串），`apply_patch_call` 和 `shell_call` 可能是 **dict**（`operation{type,path,diff}` / `action{commands}`）；`apply_patch_call_output`/`shell_call_output` 带 `status` | 源码 `stream_events.py`、`items.py`；`ScriptedModel` 实测 |
| ✅ 已验证（2026-09-27） | 取消：`RunResultStreaming.cancel(mode="immediate")` 取消后台任务、清空队列，`stream_events()` 随即正常结束（不抛异常）；`mode="after_turn"` 等本次模型调用和工具执行完再停 | 源码 `result.py`；实测 |
| ✅ 已验证（2026-09-27） | `Runner.run_streamed` 的 `max_turns` 默认 10（模型调用次数），超过抛 `MaxTurnsExceeded` | 源码 `run.py` |
| ✅ 已验证（2026-09-27） | SDK 自带测试替身 `agents.testing.ScriptedModel`：按脚本返回 `ModelStep`（输出条目、usage、错误、`respond(responder)` 动态响应、`stream(events)` 自定义流事件）。自动流式只支持 message、function_call、apply_patch_call、reasoning 条目；`shell_call` 需用 `ModelStep.stream([...])` 手写 `response.output_item.done` + `response.completed` 事件 | 源码 `testing/model.py` |
| ✅ 已验证（2026-09-27） | 追踪默认开启且会上传到 OpenAI；`RunConfig(tracing_disabled=True)` 关闭 | 源码 `run_config.py` |

## 本项目的用法（T10）

- `provider=openai` → `OpenAIResponsesModel` + 原生 `ApplyPatchTool`（`WorkspaceApplyPatchEditor`）+ `ShellTool`（`LocalShellExecutor`，cwd 为工作区，单条命令默认超时 120 秒、上限 600 秒，输出截断 2 万字符，名字含 KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL 的环境变量不传给子进程）；`allow_web` 时加 `WebSearchTool`。Shell 没有沙箱，越界改动靠轮末 `guard` 还原。
- `provider=litellm` → `LitellmModel` + 兜底文件工具（`list_files`/`read_file`/`write_file`/`edit_file`），无 Shell、无联网工具。
- 会话：`<data_dir>/openai_sessions.db`，首轮生成新 id 作为 `resume_ref`；发给模型的历史只保留最近 `Settings.openai_history_turns`（默认 20）轮，按用户消息切分。
- 用量：每次模型调用一个 `Usage` 事件，成本 = `input_tokens × price_input + output_tokens × price_output`，单价单位为**美元 / 百万 token**；缓存命中的输入按普通输入价计（宁可高估）。配置了 `max_cost_per_turn` 却缺单价时本轮直接失败。
- `RunConfig(tracing_disabled=True)`、`max_turns=200`（步数预算由 TurnRunner 强制）。
