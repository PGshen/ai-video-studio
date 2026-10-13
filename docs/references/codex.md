# Codex CLI（ChatGPT 本机登录）

用 ChatGPT 订阅登录驱动 Codex 作为第三种运行时的可行性实测，见计划 [codex-login-spike](../plans/active/codex-login-spike.md)。本文件只记录实测过的行为；结论和取舍见计划的 T5 与随后的 ADR。

实测环境：macOS 15（Darwin 24.6），ChatGPT 桌面版自带的 `codex-cli 0.162.0-alpha.17.2`。入口 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` 是一个 shell 包装，真正的可执行文件在同目录 `../CodexCLI.app/Contents/MacOS/codex`。下文的"二进制字符串"指对这个可执行文件 `strings` 后的检索结果。探针脚本和原始证据在 `data/evidence/codex-spike/`（不入库），文件名前缀即下表"来源"里的标签。

## 认证与进程环境

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | `codex login status` 显示 `Logged in using ChatGPT`；`~/.codex/auth.json` 的 `auth_mode` 为 `chatgpt`。子进程方式的 `codex exec --json` 直接沿用这份登录，无需任何 key | `t1a-minimal` |
| ✅ 已验证（2026-10-13） | 环境里有 `OPENAI_API_KEY`（假值）时**不影响**登录模式，一轮正常完成 | `t1e-fake-openai-key` |
| ✅ 已验证（2026-10-13） | 环境里有 `CODEX_API_KEY` 时**覆盖**登录：用它调 `api.openai.com/v1/responses`，假值得到 401 `invalid_api_key`。所以登录模式必须置空 `CODEX_API_KEY`（探针置空所有 `OPENAI_*`、`CODEX_*` 和名字像密钥的变量） | `t1f-fake-codex-key` |
| ✅ 已验证（2026-10-13） | `CODEX_HOME` 指向空目录时读不到登录，以无凭据身份调 `api.openai.com`，401 `Missing bearer or basic authentication`。**失败很慢**：websocket 重连 5 次再回落 HTTP，约 75–85 秒后才 `turn.failed`，运行时需要自己的超时 | `t1d-codex-home-empty` |
| ✅ 已验证（2026-10-13） | `--ignore-user-config` 不加载 `$CODEX_HOME/config.toml`（用户的插件、notify、memories、`service_tier` 等），但认证仍用 `CODEX_HOME`；同一提示的输入从 21826 token 降到 17163 | `t1a-minimal` 对比 `t1g-with-user-config` |
| ✅ 已验证（2026-10-13） | 会话文件落在 `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<时间>-<thread_id>.jsonl`（登录模式即 `~/.codex/sessions/`），与 Claude 登录模式会话落在 `~/.claude/projects/` 同理；`--ephemeral` 不写会话文件（不能续会话） | `t1a-minimal`、`codex exec --help` |
| ✅ 已验证（2026-10-13） | 不在 git 仓库里运行需要 `--skip-git-repo-check`，否则拒绝启动 | `codex exec --help` |

## 模型

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | 不传 `-m` 时（含 `--ignore-user-config`）用 `gpt-6.1-sol`（会话文件 `turn_context.model`）。`-m gpt-6-luna` 正常完成。可选模型见 `~/.codex/models_cache.json` 的 `models[].slug`（`visibility: list` 的有 `gpt-6.1-sol`、`gpt-6-astra`、`gpt-6-sol`、`gpt-6-luna`、`gpt-5.6-sol/terra/luna`、`gpt-5.5`） | `t1a-minimal`、`t1b-model-luna` |
| ✅ 已验证（2026-10-13） | 不存在的模型名：先出一条 `item.completed`（`type: error`，"Model metadata ... not found"），随后 `error` + `turn.failed`，消息为 400 `The '<名字>' model is not supported when using Codex with a ChatGPT account.`；退出码 1，约 22 秒 | `t1c-model-bogus` |
| ✅ 已验证（2026-10-13） | stderr 经常出现 `failed to refresh available models: request timed out`（每次约 5 秒超时），不影响本轮完成 | 各次运行的 `.stderr.txt` |

## 事件格式（`codex exec --json`）

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | stdout 每行一个 JSON。最小一轮依次为 `thread.started`（`thread_id`）、`turn.started`、`item.completed`（`item.type: agent_message`，`item.text`）、`turn.completed`（`usage`）。失败轮为 `error`（`message`）若干、`turn.failed`（`error.message`），退出码 1 | `t1a-minimal`、`t1c`、`t1d` |
| ✅ 已验证（2026-10-13） | `usage` 字段：`input_tokens`、`cached_input_tokens`、`cache_write_input_tokens`、`output_tokens`、`reasoning_output_tokens`。**没有成本字段**，登录模式下成本只能按 token 估算或不记 | `t1a-minimal` |
| ✅ 已验证（2026-10-13） | 配置警告（未识别的 `-c` 键、启用了开发中的 feature）以 `item.completed`（`type: error`）出现在 `turn.started` 之前，不导致失败；运行时要区分它和真正的错误 | `t1h`、`t1i` |
| ✅ 已验证（2026-10-13） | stdin 为 `/dev/null` 时 stderr 打印 `Reading additional input from stdin...`，无害 | 各次运行 |
| ✅ 已验证（2026-10-13） | 单轮"回复 ok"端到端 28–44 秒，首个事件 0.3–13 秒（Claude 本机登录同类请求约 12–14 秒）；基础指令约 2.2 万字符，最小上下文仍有约 1.1 万输入 token | `t1a`–`t1j` 的 `.meta.json` |

## 续会话、取消与用量

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | 续会话：`codex exec <exec 级参数> resume <thread_id> "<提示>"`（`--json`、`-s`、`-C`、`--skip-git-repo-check` 放在 `resume` 之前；`resume` 子命令自己只接受 `-c`、`--enable/--disable`、`-m`、`-i` 等）。续上后 `thread.started` 给出同一个 `thread_id`，模型正确复述上一轮的背景；会话仍写在同一个 rollout 文件里 | `t2a-turn1`、`t2b-resume` |
| ✅ 已验证（2026-10-13） | **`turn.completed.usage` 是整个会话的累计值**，不是本轮值：同一会话三轮的 `input_tokens` 依次为 9827 → 19692 → 33133，`output_tokens` 18 → 28 → 37。本轮用量要像 ClaudeRuntime 那样对累计值求差 | `t2a`、`t2b`、`t2c` |
| ✅ 已验证（2026-10-13） | 续会话时用 `-m` 换模型（`gpt-6.1-sol` → `gpt-6-luna`）能续上，模型正确复述；`turn.started` 之前多一条 `item.completed`（`type: error`）警告"recorded with model ... resuming with ..."，不影响完成 | `t2c-resume-switch-model` |
| ✅ 已验证（2026-10-13） | 命令执行的事件：`item.started`（`item.type: command_execution`，`command` 为 `/bin/zsh -lc '<命令>'`，`status: in_progress`），完成时 `item.completed` 带 `aggregated_output`、`exit_code` | `t2d-cancel-*` |
| ✅ 已验证（2026-10-13） | **取消用 SIGINT**：命令执行中发 SIGINT，codex 约 2.4 秒后退出（退出码 1），**会收掉自己启动的命令进程**；SIGTERM（退出码 -15）和杀进程组（SIGKILL，-9）都会留下孤儿命令进程（`/bin/zsh -c ...` 和其子进程，父进程变成 1）——codex 把命令放在**独立的进程组**里，杀 codex 所在进程组够不着。三种方式都**没有** `turn.completed`/用量事件 | `t2d-cancel-INT/TERM/KILLPG`，`ps` 观察 |
| ✅ 已验证（2026-10-13） | 被取消的会话（三种方式）都能 `resume` 续上，模型知道上一条命令被中断；续上那一轮的累计用量**包含被取消那一轮的消耗**（例如 SIGKILL 后下一轮 `input_tokens` 19885，约为两次模型调用）。所以 ClaudeRuntime 的"没拿到结果就标 `unsettled`，下一轮差值含上一轮残余"可以照搬 | `t2e-after-cancel-*` |

## 注入的上下文与收口

默认情况下，Codex 会把很多与本项目无关的内容注入每一轮。下表是逐项关闭的结果（会话文件里 `response_item` 的 developer/user 消息）。

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | **项目 AGENTS.md 会被注入**：工作区在本仓库 `data/` 下时，Codex 从 cwd 往上找到仓库根的 `AGENTS.md` 并整段注入（`--ignore-user-config` 也照样注入）。`-c project_doc_max_bytes=0` 关闭 | `t1a-minimal` 对比 `t1h-minimal-context` |
| ✅ 已验证（2026-10-13） | **用户 skills 会被注入**：`~/.codex/skills`、`~/.agents/skills`、`~/.codex/skills/.system` 下的 skill 列表（本机 23 个，约 6.6K 字符，含开发用的 superpowers）。`-c skills.include_instructions=false` 关闭（键名来自二进制字符串 `SkillsConfig{bundled, include_instructions, max_context_tokens}`）；`include_skills_usage_instructions` 等是模型目录字段，用 `-c` 传会被报"未识别" | `t1i` 对比 `t1j-minimal-context3` |
| ✅ 已验证（2026-10-13） | `-c include_collaboration_mode_instructions=false` 去掉协作模式段；`--disable plugins`/`--disable apps` 等去掉插件推荐段 | `t1h-minimal-context` |
| ✅ 已验证（2026-10-13） | `-c 'developer_instructions="..."'` 作为第一条 developer 消息注入——阶段系统提示可以走这里 | `t1i-minimal-context2` |
| ✅ 已验证（2026-10-13） | **多 agent 关不掉**：`--disable multi_agent --disable multi_agent_v2 -c agents.max_depth=0` 之后仍有 `<multi_agent_role>` 段（约 2.4K 字符）和 `spawn_agent`、`send_message`、`wait_agent` 等工具；`agents.max_threads=0` 被拒（`max_concurrent_threads_per_session must be at least 1`） | `t1j-minimal-context3` |
| ✅ 已验证（2026-10-13） | 收口后模型自述的工具：`exec_command`、`write_stdin`、`apply_patch`、`view_image`、`list_mcp_resources`/`list_mcp_resource_templates`/`read_mcp_resource`、`request_user_input`(+`_async`)、`wait`、`exec`、`clock.sleep`、`clock__curr_time`、`collaboration.*`。`-c 'web_search="disabled"'` 后不再有网页搜索 | `t1j-minimal-context3` |
| ⚠️ 待验证（T3） | 能否进一步去掉 `collaboration.*`、`request_user_input` 等工具（二进制里有 `ToolsToml` 及 `enabled_tools` 字段名，用法未知）；`model_instructions_file` 能否替换约 2.2 万字符的基础指令 | 计划 T3 |

本节的最小上下文参数组合（T2 之后的探针统一使用）：

```
exec --json --skip-git-repo-check --ignore-user-config
  -c project_doc_max_bytes=0 -c skills.include_instructions=false -c skills.bundled.enabled=false
  -c include_apps_instructions=false -c include_collaboration_mode_instructions=false
  -c 'web_search="disabled"' -c 'developer_instructions="<阶段系统提示>"'
  --disable multi_agent --disable plugins --disable apps --disable memories --disable skill_search
  --disable tool_suggest --disable image_generation --disable browser_use --disable computer_use --disable goals
```
