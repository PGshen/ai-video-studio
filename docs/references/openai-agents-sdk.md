# OpenAI Agents SDK（Python，`openai-agents`）

用于 `agent/` 中的 OpenAIRuntime。旧项目锁定的版本是 `openai-agents 0.22.0`，新项目以实际安装的版本为准，安装后在这里注明版本号。

## 事实

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-09-26） | 托管工具（`WebSearchTool`、`FileSearchTool`、`CodeInterpreterTool`、`ImageGenerationTool`、`HostedMCPTool` 等）**只能**配合 Responses API（`OpenAIResponsesModel`）使用，不兼容 Chat Completions 和 LiteLLM | [官方 Tools 文档](https://openai.github.io/openai-agents-python/tools/) |
| ✅ 已验证（2026-09-26） | 本地执行的工具有：`ShellTool`（需要提供 executor，也支持托管容器）、`ApplyPatchTool`（需要实现 `ApplyPatchEditor`）、`ComputerTool`、`LocalShellTool`（旧版） | 同上 |
| ⚠️ 待验证 | 官方文档称本地工具"适用于任何模型后端"，但 `shell`/`apply_patch` 依赖模型经过相应训练；通过 LiteLLM 接入的 DeepSeek、豆包能否正确使用未知 | 同上；M1 冒烟测试时验证（R1） |
| ✅ 已验证（2026-09-26） | 函数工具可以返回图片（`ToolOutputImage`）或文件（`ToolOutputFileContent`），可以和文本一起返回 | 同上 |
| ⚠️ 待验证 | 非 OpenAI 模型返回图片工具输出时的表现 | M1 冒烟测试时验证（R2） |
| ⚠️ 待验证 | 会话记忆可以使用 SDK 自带的 `SQLiteSession(session_id, db_path)` | 推断，M1 验证 |
| ⚠️ 待验证 | 旧项目的写法：`AsyncOpenAI(api_key, base_url, timeout)` + `OpenAIResponsesModel`，通过 `Runner.run_streamed(..., max_turns=...)` 流式运行；预算通过 `RunHooks`（`on_llm_end` 中累计用量）控制 | 旧项目 `../ai-video/backend/app/services/strategies/openai_agent_runtime.py` |
