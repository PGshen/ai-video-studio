# Codex CLI（ChatGPT 本机登录）

用 ChatGPT 订阅登录驱动 Codex 作为第三种运行时的可行性实测，见计划 [codex-login-spike](../plans/active/codex-login-spike.md)。本文件只记录实测过的行为；结论和取舍见计划的 T5 与随后的 ADR。

实测环境：macOS 15（Darwin 24.6），ChatGPT 桌面版自带的 `codex-cli 0.162.0-alpha.17.2`。入口 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` 是一个 shell 包装，真正的可执行文件在同目录 `../CodexCLI.app/Contents/MacOS/codex`。下文的"二进制字符串"指对这个可执行文件 `strings` 后的检索结果。探针脚本和原始证据在 `data/evidence/codex-spike/`（不入库），文件名前缀即下表"来源"里的标签。

## 结论摘要（2026-10-13）

- ChatGPT 本机登录能以子进程方式驱动 `codex exec --json`，多轮续会话、换模型、取消后续上都可行。
- 需要收口的地方都有对应办法：关闭注入的上下文（AGENTS.md、skills、插件等）、用 MCP 的 `enabled_tools` 做工具白名单、用 permission profile 做读隔离和写隔离、断网。
- 做不到或要注意的地方：多 agent 工具关不掉；`developer_instructions` 只在建会话时生效；用量是累计 token、没有成本字段；取消必须用 SIGINT；单轮比 Claude 慢 2–3 倍；CLI 是随 ChatGPT 桌面版更新的 alpha 版，部分配置键来自二进制字符串，没有官方文档。
- 取舍见 [ADR 0030](../decisions/0030-Codex本机登录运行时.md)。

## 认证与进程环境

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | `codex login status` 显示 `Logged in using ChatGPT`；`~/.codex/auth.json` 的 `auth_mode` 为 `chatgpt`。子进程方式的 `codex exec --json` 直接沿用这份登录，无需任何 key | `t1a-minimal` |
| ✅ 已验证（2026-10-13） | 环境里有 `OPENAI_API_KEY`（假值）时**不影响**登录模式，一轮正常完成 | `t1e-fake-openai-key` |
| ✅ 已验证（2026-10-13） | 环境里有 `CODEX_API_KEY` 时**覆盖**登录：用它调 `api.openai.com/v1/responses`，假值得到 401 `invalid_api_key`，同样重连约 86 秒后才 `turn.failed`。所以登录模式必须置空 `CODEX_API_KEY`（探针置空所有 `OPENAI_*`、`CODEX_*` 和名字像密钥的变量） | `t1f-fake-codex-key` |
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
| ✅ 已验证（2026-10-13） | 单轮"回复 ok"端到端 28–44 秒，首个事件 0.3–13 秒（Claude 本机登录同类单轮极小请求约 12–14 秒，见 [claude-agent-sdk.md](claude-agent-sdk.md) 中 `model_not_found` 一行）；基础指令约 2.2 万字符，最小上下文仍有约 1.1 万输入 token | `t1a`–`t1j` 的 `.meta.json` |

## 续会话、取消与用量

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | 续会话：`codex exec <exec 级参数> resume <thread_id> "<提示>"`（`--json`、`-s`、`-C`、`--skip-git-repo-check` 放在 `resume` 之前；`resume` 子命令自己只接受 `-c`、`--enable/--disable`、`-m`、`-i` 等）。续上后 `thread.started` 给出同一个 `thread_id`，模型正确复述上一轮的背景；会话仍写在同一个 rollout 文件里 | `t2a-turn1`、`t2b-resume` |
| ✅ 已验证（2026-10-13） | **`turn.completed.usage` 是整个会话的累计值**，不是本轮值：同一会话三轮的 `input_tokens` 依次为 9827 → 19692 → 33133，`output_tokens` 18 → 28 → 37。本轮用量要像 ClaudeRuntime 那样对累计值求差 | `t2a`、`t2b`、`t2c` |
| ✅ 已验证（2026-10-13） | 续会话时用 `-m` 换模型（`gpt-6.1-sol` → `gpt-6-luna`）能续上，模型正确复述；`turn.started` 之前多一条 `item.completed`（`type: error`）警告"recorded with model ... resuming with ..."，不影响完成 | `t2c-resume-switch-model` |
| ✅ 已验证（2026-10-13） | 命令执行的事件：`item.started`（`item.type: command_execution`，`command` 为 `/bin/zsh -lc '<命令>'`，`status: in_progress`），完成时 `item.completed` 带 `aggregated_output`、`exit_code` | `t2d-cancel-*` |
| ✅ 已验证（2026-10-13） | **取消用 SIGINT**：命令执行中发 SIGINT，codex 收尾后退出（退出码 1，实测 2.4 秒；收尾期间还会再发一次模型请求，会话里随后记 `turn_aborted`，所以耗时不固定），**会收掉自己启动的命令进程**；SIGTERM（退出码 -15）和杀进程组（SIGKILL，-9）都会留下孤儿命令进程（`/bin/zsh -c ...` 和其子进程，父进程变成 1）——codex 把命令放在**独立的进程组**里，杀 codex 所在进程组够不着（探针 `.meta.json` 的 `process_group_alive_after_exit` 只检查 codex 自己的进程组，所以是 false）。三种方式都**没有** `turn.completed`/用量事件 | `t2d-cancel-*`（三者并发，`ps` 观察未存证）；单独复测 `t2f-cancel-TERM-solo` + `t2f-ps-TERM.txt`（SIGTERM 后留下 ppid=1、独立 pgid 的 `/bin/zsh -c sleep 60 ...`）、`t2g-cancel-INT-solo` + `t2g-ps-INT.txt`（SIGINT 后无新增残留） |
| ✅ 已验证（2026-10-13） | 被取消的会话（三种方式）都能 `resume` 续上，模型知道上一条命令被中断；续上那一轮的累计用量**包含被取消那一轮的消耗**（例如 SIGKILL 后下一轮 `input_tokens` 19885，约为两次模型调用）。所以 ClaudeRuntime 的"没拿到结果就标 `unsettled`，下一轮差值含上一轮残余"可以照搬。TERM/KILL 后续会话时 stderr 有 `Custom tool call output is missing for call id`，codex 会自动补齐缺失的工具输出 | `t2e-after-cancel-*` |

## 业务工具（MCP）

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | stdio MCP server 用 `-c 'mcp_servers.<名字>.command="<可执行文件>"'`、`-c 'mcp_servers.<名字>.args=["..."]'` 传入即可，不需要改 `config.toml`。服务器配置的其他字段（二进制字符串 `RawMcpServerConfig`）：`env`、`env_vars`、`cwd`、`url`、`bearer_token_env_var`、`http_headers`、`startup_timeout_sec`、`tool_timeout_sec`、`enabled_tools`、`disabled_tools`、`default_tools_approval_mode`、`required` 等 | `t3a-mcp`、`t3b-mcp-approve` |
| ✅ 已验证（2026-10-13） | **MCP 工具默认需要审批**：`approval_policy=never` 下调用直接失败（`item.completed` 的 `mcp_tool_call.error.message` 为 `MCP tool call requires approval, but approval policy is never`，两次调用都是 `status: failed`，没有到达服务器）。要加 `-c 'mcp_servers.<名字>.default_tools_approval_mode="approve"'`（取值见二进制字符串 `AppToolApproval`：`auto`/`writes`/`approve`） | `t3a-mcp` 对比 `t3b-mcp-approve` |
| ✅ 已验证（2026-10-13） | 事件：`item.started`/`item.completed`，`item.type: mcp_tool_call`，字段 `server`、`tool`（不带前缀的工具名）、`arguments`、`result.content`（MCP content 原样，图片为 `{"type":"image","data":<base64>,"mimeType":"image/png"}`）、`result.structured_content`、`error`、`status`（`in_progress`/`completed`/`failed`） | `t3b-mcp-approve` |
| ✅ 已验证（2026-10-13） | 模型**看得到** MCP 工具返回的图片：左蓝右黄的 PNG（文字不提颜色），模型答出"左半边蓝色、右半边黄色" | `t3b-mcp-approve` |
| ✅ 已验证（2026-10-13） | `-c 'mcp_servers.<名字>.enabled_tools=["lookup_note"]'` 生效：未开放的 `render_swatch` 模型看不到（模型报告"不存在"），服务器也没收到调用。可以用它实现阶段工具白名单 | `t3d-enabled-tools` |
| ⚠️ 观察（2026-10-13，未存证） | codex 退出后 stdio MCP server 进程随之退出，没有残留 | `pgrep` 观察 |
| ⚠️ 待验证 | 接入形态：业务工具需要访问后端的项目、快照等状态。两种形态：① stdio 桥接进程（`python -m <桥接模块>`，经本机 HTTP 回调后端，凭本轮令牌鉴权）；② 后端直接提供 streamable HTTP MCP 端点，codex 用 `url` + `bearer_token_env_var` 连接（不需要额外进程，但要确认 codex 的 HTTP MCP 在登录模式下可用、令牌如何轮换）。两者都未实测 | 方案描述 |

## 注入的上下文与收口

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | **`developer_instructions` 只在新建会话时注入**：`resume` 时传入新的 `developer_instructions` 不会出现在会话里，模型仍只看到建会话时的那一条。所以阶段系统提示固定在会话创建时；同一会话中途换阶段或改提示词，需要新建会话或把变化放进用户消息 | `t3e-resume-devinstr` 的会话文件 `~/.codex/sessions/2026/10/13/rollout-*-01a1344e-8046-*.jsonl`（jsonl 只有回复 ok） |

默认情况下，Codex 会把很多与本项目无关的内容注入每一轮。下表是逐项关闭的结果（会话文件里 `response_item` 的 developer/user 消息）。

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | **项目 AGENTS.md 会被注入**：工作区在本仓库 `data/` 下时，Codex 从 cwd 往上找到仓库根的 `AGENTS.md` 并整段注入（`--ignore-user-config` 也照样注入）。`-c project_doc_max_bytes=0` 关闭 | `t1a-minimal` 对比 `t1h-minimal-context` |
| ✅ 已验证（2026-10-13） | **用户 skills 会被注入**：`~/.codex/skills`、`~/.agents/skills`、`~/.codex/skills/.system` 下的 skill 列表（本机 23 个，约 6.6K 字符，含开发用的 superpowers）。`-c skills.include_instructions=false` 关闭（键名来自二进制字符串 `SkillsConfig{bundled, include_instructions, max_context_tokens}`）；`include_skills_usage_instructions` 等是模型目录字段，用 `-c` 传会被报"未识别" | `t1i` 对比 `t1j-minimal-context3` |
| ✅ 已验证（2026-10-13） | `-c include_collaboration_mode_instructions=false` 去掉协作模式段；`--disable plugins`/`--disable apps` 等去掉插件推荐段 | `t1h-minimal-context` |
| ✅ 已验证（2026-10-13） | `-c 'developer_instructions="..."'` 作为第一条 developer 消息注入——阶段系统提示可以走这里 | `t1i-minimal-context2` |
| ✅ 已验证（2026-10-13） | **多 agent 关不掉**：`--disable multi_agent --disable multi_agent_v2 -c agents.max_depth=0` 之后仍有 `<multi_agent_role>` 段（约 2.4K 字符；同时有一条 `<multi_agent_mode>` 段要求“除非用户明确要求，不要派生子 agent”，说明开关部分生效）和 `spawn_agent`、`send_message`、`wait_agent` 等工具；`agents.max_threads=0` 被拒（`max_concurrent_threads_per_session must be at least 1`） | `t1j-minimal-context3` |
| ✅ 已验证（2026-10-13） | 收口后模型自述的工具：`exec_command`、`write_stdin`、`apply_patch`、`view_image`、`list_mcp_resources`/`list_mcp_resource_templates`/`read_mcp_resource`、`request_user_input`(+`_async`)、`wait`、`exec`、`clock.sleep`、`clock__curr_time`、`collaboration.*`。`-c 'web_search="disabled"'` 后不再有网页搜索 | `t1j-minimal-context3` |
| ✅ 已验证（2026-10-13） | 收口后模型看到的工具名带命名空间（`functions.exec`/`functions.wait` 是 code mode，`tools.*` 是内置工具，`collaboration.*` 是多 agent），由模型目录的 `tool_mode` 决定。`--disable code_mode_host` 会让 code mode "fail closed"（`item.completed` 错误，工具列表不变），**不能用**；`tools.update_plan`、`tools.experimental_request_user_input` 是结构体，传布尔值会让 codex 启动即失败（`invalid type: boolean`）；`-c tools.update_plan.enabled=false` 被接受。结论：**这个版本无法通过配置去掉 `collaboration.*`、`functions.request_user_input`**；`request_user_input` 在 exec 模式下本来就不支持（二进制字符串 `request_user_input is not supported in exec mode`） | `t3c-lockdown` |
| ⚠️ 待验证 | `model_instructions_file` 能否替换约 2.2 万字符的基础指令（二进制里有此键，未实测；替换后工具使用说明可能丢失） | 二进制字符串 |

本节的最小上下文参数组合（T2 之后的探针统一使用）：

```
exec --json --skip-git-repo-check --ignore-user-config
  -c project_doc_max_bytes=0 -c skills.include_instructions=false -c skills.bundled.enabled=false
  -c include_apps_instructions=false -c include_collaboration_mode_instructions=false
  -c 'web_search="disabled"' -c 'developer_instructions="<阶段系统提示>"'
  --disable multi_agent --disable plugins --disable apps --disable memories --disable skill_search
  --disable tool_suggest --disable image_generation --disable browser_use --disable computer_use --disable goals
```

## 沙箱与读隔离（macOS）

探测脚本 `ws-t4/probe.sh` 逐项尝试读写并只打印 OK/DENIED（读用 `wc -c`，不输出内容）；工作区 `ws-t4`，兄弟目录 `ws-t4-other` 模拟数据目录里的其他项目。

| 状态 | 内容 | 来源 |
|---|---|---|
| ✅ 已验证（2026-10-13） | `-s workspace-write`（`approval_policy` 在 exec 模式下即 `never`）：工作区可写；仓库根、兄弟项目不可写；`$TMPDIR` 和 `/tmp` **可写**；**默认断网**（`curl` 失败，会话里 `network_access: false`）；**读完全不受限**——兄弟项目、`backend/.env`、仓库 `AGENTS.md`、`~/.ssh`、`~/.codex/auth.json`（ChatGPT 登录的 OAuth token）都能读 | `t4a-workspace-write` |
| ✅ 已验证（2026-10-13） | **permission profile 能做读隔离**，用 `-c` 定义、不改 `config.toml`：`-c 'permissions.studio.extends=":workspace"'`、`-c 'permissions.studio.filesystem={"<仓库根>"="deny", "<工作区>"="write", "~/.ssh 绝对路径"="deny", "~/.codex 绝对路径"="deny", ":tmpdir"="read", ":slash_tmp"="read"}'`、`-c 'default_permissions="studio"'`，且**不能再传 `-s`**（`sandbox_mode` 与 `default_permissions` 互斥）。效果：工作区可写；`$TMPDIR`、`/tmp`、兄弟项目、仓库根不可写；兄弟项目、`.env`、`AGENTS.md`、`~/.ssh`、`~/.codex/auth.json` 不可读；断网；`python3` 等工具照常可用。"拒读父目录、放回子目录"可行（更具体的路径优先），与 Claude 路径的 `denyRead`+`allowRead` 同一策略 | `t4b-profile-deny`、`t4c-profile-tmp` |
| ✅ 已验证（2026-10-13） | 会话 `turn_context.permission_profile` 记录展开后的条目：内置 `:workspace` 自带 `root` 可读、`slash_tmp`/`tmpdir` 可写、cwd 可写，再叠加自定义条目；内置 profile 名（二进制字符串）有 `:workspace`、`:read-only`、`:danger-full-access`、`:minimal`；访问级别 `read`/`write`/`deny`/`none`；特殊路径键 `:tmpdir`、`:slash_tmp`（另有 `root`、`minimal`、`project_roots`） | `t4b-profile-deny` 的会话文件 |
| ⚠️ 部分验证（2026-10-13） | `apply_patch` 写工作区内文件成功（`item.type: file_change`，`changes[].path/kind`）；要求写工作区外的文件时文件没有被创建，但事件里只有一条成功的 `file_change`，分不清是工具拒绝还是模型没尝试。不论哪种，轮末 guard 都会还原阶段可写范围外的改动 | `t4d-apply-patch` |
| ✅ 已验证（2026-10-13） | 不需要外包 `sandbox-exec`：codex 自带的 permission profile 已能达到本项目的隔离要求，所以没有实测嵌套 Seatbelt | 结论 |
| ✅ 已验证（2026-10-13） | permission profile 只约束模型执行的命令，**不约束 MCP 子进程**：profile 拒读整个仓库根时，位于仓库内的 `backend/.venv/bin/python` 和 MCP 服务器脚本照常启动，`lookup_note` 调用成功。好处是桥接进程能读后端代码；但 MCP 工具本身没有沙箱，读写边界要由工具实现自己保证（与 Claude 路径的业务工具一致） | `t3f-profile-plus-mcp`、`mcp_calls.log` |
| ⚠️ 待验证 | codex 进程内的读文件工具（`view_image`、`read_mcp_resource`）是否受 profile 拒读约束：要求模型对拒读路径调用 `view_image` 时，模型依据权限说明**拒绝调用**（即使提示里强调要测工具本身），所以无法经由模型验证工具层面的拦截 | `t3f-profile-plus-mcp`、`t4e-view-image-denied` |
| ✅ 已验证（2026-10-13） | 偶发的网络错误以 `error` 事件出现（`Reconnecting... n/5 (workspace routing discovery failed)`），重连成功后本轮继续，不一定 `turn.failed`；运行时不能见到 `error` 事件就判失败 | `t2f-cancel-TERM-solo` |
