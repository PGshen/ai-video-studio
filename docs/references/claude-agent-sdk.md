# Claude Agent SDK（Python，`claude-agent-sdk`）

用于 `agent/` 中的 ClaudeRuntime。设计依据见[架构设计 §4](../design/2026-09-26-architecture.md)。

## 事实

| 状态 | 内容 | 来源 |
|---|---|---|
| ⚠️ 待验证 | 选项通过 `ClaudeAgentOptions` 传入，旧项目用过的字段有：`model`、`cwd`、`setting_sources=[]`（不加载本地设置文件）、`permission_mode="acceptEdits"`、`max_turns`、`max_budget_usd`、`mcp_servers`、`allowed_tools`、`tools`（可用的内置工具列表）、`env`（传入 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`）、`resume` | 旧项目 `../ai-video/backend/app/services/strategies/claude_agent_runtime.py` |
| ⚠️ 待验证 | 业务工具用 `@tool(name, description, schema)` 定义，再用 `create_sdk_mcp_server(name, version, tools)` 做成进程内 MCP server；工具返回 `{"content": [...], "is_error": bool}` | 旧项目 `agent_sandbox.py: build_validate_server` |
| ⚠️ 待验证 | 流式消息中带有 `session_id`；最终的 result 消息带有 `subtype`、`result`、`total_cost_usd`、`num_turns`，而且都是**累计值**（恢复会话后需要减去之前的值） | 旧项目 `claude_agent_runtime.py` |
| ⚠️ 待验证 | 工具返回图片：MCP 的 image content block（`{"type": "image", "data": <base64>, "mimeType": ...}`） | 推断，M1 冒烟测试时验证（R2） |
| ⚠️ 待验证 | `PreToolUse` hook 可以拦截 Write/Edit，并返回拒绝原因 | 推断，M1 验证 |
| ⚠️ 待验证 | 可以开启 sandbox 选项来限制 Bash 的文件系统访问；macOS 上的具体行为未知 | 推断，M1 验证（R3） |
| ⚠️ 待验证 | 会话存储位置可以通过环境变量（例如 `CLAUDE_CONFIG_DIR`）指向数据目录 | 推断，M1 验证（R4） |
| ⚠️ 待验证 | 中断正在运行的轮次：`ClaudeSDKClient.interrupt()`；使用 `query()` 时只能关闭流 | 推断，M1 验证 |
| ✅ 已验证（2026-09-27） | 官方政策：除非事先获批，Anthropic 不允许第三方开发者在其产品（包括基于 Agent SDK 构建的 agent）中提供 claude.ai 登录或订阅额度，应使用 API key 认证（也支持 Bedrock / Vertex 等云厂商认证） | [Agent SDK Overview](https://docs.claude.com/en/docs/agent-sdk/overview) |
| ⚠️ 待验证 | 技术上 SDK 通过子进程调用 Claude Code CLI；未设置 `ANTHROPIC_API_KEY` 时，CLI 会沿用本机已登录的凭据（订阅账号）。若把 `CLAUDE_CONFIG_DIR` 指向数据目录（R4），可能读不到原有登录状态 | 推断，T9 读源码、T15 实测 |
