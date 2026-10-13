# codex-runtime：用 ChatGPT 本机登录驱动 Codex 的第三种运行时

<!-- 只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 零散需求（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [ADR 0030](../../decisions/0030-Codex本机登录运行时.md)（已采纳，四条前提已接受）；已验证行为见 [codex.md](../../references/codex.md)；运行时分层沿用 [架构设计 §4.1–§4.3](../../design/2026-09-26-architecture.md) |
| 分支 | `codex-runtime` |
| 批准记录 | 2026-10-13：负责人批准计划，Native 执行 |

## 目标

设置页可以新建（并内置一条）`runtime=codex` 的模型配置，不填 API key，用本机 ChatGPT 订阅登录驱动 Codex CLI。各阶段会话选它之后可以多轮对话、调用业务工具、读写工作区、取消、换同供应商的模型；隔离强度与 Claude 本机登录相当；用量按 token 记录。

## 范围

**包含：**

- 使用 ChatGPT 桌面版自带的 Codex CLI（spike 实测的就是它，`0.162.0-alpha.17.2`）；`STUDIO_CODEX_BIN` 可以改用别的 CLI。版本漂移由配置警告提示和冒烟里的版本对比兜底（ADR 0030 前提 2，2026-10-13 改定）。
- 补测 spike 没测的思考强度参数。
- 业务工具经 MCP 提供给 codex；先实测两种接法再选定（ADR 0030「业务工具」）。
- `CodexRuntime`：启动 `codex exec --json`、事件映射、续会话、累计用量求差、阶段系统提示的注入与变更处理、图片输入。
- 取消（SIGINT → 宽限 → 强杀 + 孤儿清理）。
- permission profile 生成（读隔离、写隔离、断网）与隔离测试；非 macOS 按 ADR 0024 的无隔离开关处理。
- 模型配置 `runtime=codex`（只允许登录模式）、内置配置 `codex-login`、设置页、连通性测试、会话自动命名、附件说明、联网策略。
- `make smoke` 的 codex 用例、references、QUALITY、runbook。

**不包含：**

- `CODEX_API_KEY`（API key 计费）模式：没有授权付费调用，`runtime=codex` 只允许 `api_key_env` 为空。
- `codex app-server`（JSON-RPC）形态（ADR 0030 已放弃）。
- Windows/Linux 上的实测与沙箱适配：只做到"没有可用沙箱时按无隔离开关处理"，Windows 实测另立 TODO。
- 替换 codex 的基础指令（`model_instructions_file`，未验证）。
- 去掉 `collaboration.*` 多 agent 工具（这个版本做不到，只在提示里禁止并在事件流里检测）。
- 把 codex 会话文件从 `~/.codex/sessions/` 挪走（改 `CODEX_HOME` 会读不到登录，ADR 0030）。

## 全局约束

- **安全**：`~/.codex/auth.json` 只读，任何日志、证据、测试输出、错误信息里都不出现其中的 token；不修改 `~/.codex/config.toml`；不复制 `auth.json`；`CODEX_HOME` 保持默认。
- **付费调用**：只用 ChatGPT 登录跑真实模型（不产生 API 费用，负责人已在 ADR 0030 接受，**本计划预先授权**，不限次数，但每次冒烟尽量用极小提示以节省订阅额度）。不设置 `CODEX_API_KEY`，不用任何 OpenAI API key 调 codex。
- **新依赖（本计划写明，仅此一项）**：
  - Python `mcp>=1.30,<2` 写进 `backend/pyproject.toml`（目前已作为 `claude-agent-sdk` 的传递依赖装着 1.30.0；业务代码要直接 import 它，所以显式声明）。只有 T2 选定"后端内置 HTTP MCP"时才需要 HTTP 服务端相关模块。
- **CLI 定位**：`STUDIO_CODEX_BIN` 设了就用它（文件不存在时不回落）；否则用 ChatGPT 桌面版自带的 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`（或 `~/Applications/` 下同一路径，仅 macOS）；都没有时 `codex` 运行时不注册，设置页测试给出"未找到 Codex CLI：安装 ChatGPT 桌面版或设置 STUDIO_CODEX_BIN"。不搜 PATH。
- **子进程环境**：置空所有 `OPENAI_*`、`CODEX_*`、`AZURE_OPENAI*`、`ANTHROPIC_*`、`CLAUDE_CODE_*` 及名字像密钥的变量（`KEY`/`TOKEN`/`SECRET`/`PASSWORD`/`CREDENTIAL`）；与 spike 探针一致。
- **上下文收口**：每次启动都带 `--ignore-user-config`、`--skip-git-repo-check` 和 codex.md「本节的最小上下文参数组合」。
- **超时**：codex 认证失败要约 80 秒才报错；连通性测试超时 120 秒（Claude/OpenAI 仍是 30 秒）。
- **工作约定**：测试先行；`make check` 绿；一个任务至少一个 commit，`<type>(<scope>): <中文说明>`；不改 `docs/design/`。

## 接口

- `ModelProfile.runtime` 新增取值 `codex`；`USER_RUNTIMES = ("claude", "openai", "codex")`；`codex` 只接受 `api_key_env = null`。前端 `USER_RUNTIMES` 同步。
- 内置配置 `codex-login`：`provider=openai`、`runtime=codex`、`model=gpt-6.1-sol`、`api_key_env=null`、`supports_vision=true`、无单价。
- `Settings.codex_bin: Path | None`（`STUDIO_CODEX_BIN`）。
- `register_codex(factory, settings)`：找到 CLI 才注册 `codex`。
- 会话 `sdk_ref` 存 codex 的 `thread_id`。
- 运行时私有状态：`<data_dir>/codex/ledger/<thread_id>.json`，含上次累计 usage、`unsettled`、建会话时系统提示的哈希。
- 现有 HTTP 接口形状不变。

## 验收标准

- [ ] AC1：本机找得到桌面版自带的 CLI，`STUDIO_CODEX_BIN` 能覆盖；都找不到时 `codex` 运行时不注册，设置页测试显示可读的原因；配置警告（未识别的键）进日志并在界面提示。（验证：单元测试 + 设置 `STUDIO_CODEX_BIN` 为不存在的路径后的接口测试）
- [ ] AC2：参数构造、事件映射、累计用量求差（含取消后 `unsettled` 并入下一轮）、系统提示变更、多 agent 工具检测、配置警告与真错误的区分、`error` 事件不直接判失败，都有单元测试，用录制的 JSONL 回放（不调真实模型）。（验证：`make check`）
- [ ] AC3：取消：SIGINT 后 codex 在宽限期内退出、本轮 `cancelled`、没有残留命令进程；SIGINT 不响应时强杀并清理孤儿进程组；被取消的会话下一轮能续上。（验证：单元测试用假 CLI 脚本；冒烟 `codex_login_cancel_then_turn` 加 `ps` 检查）
- [ ] AC4：隔离：模型执行的命令读不到兄弟项目、`backend/.env`、仓库 `AGENTS.md`、`~/.ssh`、`~/.codex/auth.json`，写不出工作区，`/tmp` 不可写，断网；工作区可读写。`view_image` 对拒读路径的行为有一个直接的测试结论（拦截 / 不拦截并登记风险）。（验证：冒烟 `codex_login_sandbox_read`，输出只有 OK/DENIED）
- [ ] AC5：业务工具：阶段白名单内的工具可调用、图片结果模型看得到、白名单外的工具模型看不到；工具写文件经 `record_tool_write` 记账，轮末 guard 不误还原。（验证：单元测试 + 冒烟 `codex_login_tools`）
- [ ] AC6：设置页可以新建 `codex` 配置（填 API key 环境变量时报错），列表「测试」对 `codex-login` 显示成功、耗时和回复；把模型名改成不存在的，显示 400 原因。（验证：浏览器截图）
- [ ] AC7：真实走一遍：选题或叙事阶段用 `codex-login` 新建会话，两轮对话（第二轮依赖第一轮内容）、一次业务工具调用、一次改工作区文件并生成快照、一次中途取消再继续、一次换到 `gpt-6-luna`；会话自动命名正常。（验证：浏览器截图 + api 日志摘录）
- [ ] AC8：Claude、OpenAI 两个运行时行为不变，现有测试原样通过；`make check` 全绿。

## 评审重点

测试没有直接覆盖、最可能出问题的情况（评审时逐条检查）：

1. **登录失效或未登录**：`~/.codex/auth.json` 不存在或 token 过期时，本轮应在合理时间内失败，并给出"请先在终端运行 codex login"一类的原因，而不是空错误或卡住约 80 秒无反馈。T3 加一个回放用例（401 事件序列）钉住错误文案。
2. **codex 进程异常退出（非零退出码、没有 `turn.completed` 也没有 `turn.failed`）**：本轮应 `failed` 并带 stderr 尾部（打码后），账本标 `unsettled`。T3 用假 CLI 脚本钉住。
3. **MCP 服务端生命周期**：本轮结束（含取消、异常）后本轮的 MCP 端点/桥接进程都关闭，令牌失效；并发两轮的令牌互不可用。T2 钉住。
4. **系统提示在会话中途变化**（改了风格、阶段提示词升级）：续会话时 `developer_instructions` 不生效，必须走"变更说明并入用户消息"的路径，不能静默用旧提示。T3 钉住。
5. **stdout 里的超长行**（工具返回大图、长命令输出）：JSONL 读取不能因为默认行长限制而报错中断。T3 用超过 1 MiB 的单行回放钉住。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：CLI 定位与补测（完成）

- **目标**：后端能找到要用的 Codex CLI；补测 spike 没测的思考强度参数。
- **涉及文件**：`backend/src/studio/config.py`（`codex_bin`）、`backend/src/studio/agent/codex_cli.py`（新：`desktop_candidates(platform, home) -> list[Path]`、`find_codex(override, candidates) -> Path | None`、`codex_version(bin) -> str`、`VERIFIED_VERSION`）、`backend/tests/agent/test_codex_cli.py`、`backend/tests/test_config.py`、`docs/references/codex.md`、`docs/runbooks/dev-setup.md`、ADR 0030（前提 2 改定）。
- **接口与要点**：`find_codex` 只看 `STUDIO_CODEX_BIN` 和桌面版位置，不搜 PATH；`VERIFIED_VERSION` 是 codex.md 实测所用版本，T7 冒烟拿它对比。思考强度用 `-c model_reasoning_effort="<值>"` 实测（证据前缀 `r1g`）。
- **测试**：桌面版候选路径（macOS / 其他平台为空）；`override` 优先、`override` 不存在不回落、取第一个存在的候选、都不存在；`codex_version` 解析与异常；`STUDIO_CODEX_BIN` 留空等于没设置。
- **完成标准**：上述测试通过；思考强度结论写进 codex.md。
- **验证命令**：`make check`

### T2：业务工具的 MCP 接法（实测选型 + 实现）（完成）

- **目标**：把本轮的 `ToolSpec` 列表暴露给 codex，调用经 `invoke_tool` 走现有的校验与截断；选定并实现一种接法。
- **候选**：
  - **A（推荐先测）本轮内置 HTTP MCP**：`CodexRuntime` 每轮在后端进程内起一个只监听 `127.0.0.1`、随机端口的 streamable HTTP MCP 服务（`mcp` 包），随机 bearer 令牌经子进程环境变量传给 codex（`url` + `bearer_token_env_var`），本轮结束即关闭。不需要额外进程，handler 直接拿到本轮 `ToolContext`。
  - **B stdio 桥接进程**：codex 启动 `python -m studio.agent.codex_bridge`，桥接进程再经本机回调连回后端。多一个进程和一条回调通道。
  - 先用最小服务实测 A 在登录模式下能否连上、令牌是否生效、图片 content 是否透传；A 可行就选 A，不再实现 B。结论写进 codex.md 的"接入形态"一行和本计划「决策记录」。
- **涉及文件**：`backend/pyproject.toml`、`backend/uv.lock`（显式声明 `mcp`）、`backend/src/studio/agent/codex_mcp.py`（新）、`backend/tests/agent/test_codex_mcp.py`、`docs/references/codex.md`。
- **接口与要点**：
  - `TurnToolServer`（异步上下文管理器）：`__aenter__` 返回 codex 需要的 `-c mcp_servers.studio.*` 参数片段与要注入的环境变量；`__aexit__` 关闭服务、令牌作废。
  - 工具白名单用 `enabled_tools`（= 本轮 `ctx.tools` 的名字）；`default_tools_approval_mode="approve"`；`tool_timeout_sec` 取一个足够渲染类工具完成的值（参照现有工具最长耗时，写进决策记录）。
  - `ToolResult.images` → MCP image content；`is_error` → MCP `isError`。
- **测试**：不起 codex，直接用 `mcp` 客户端连本轮服务：列工具只含白名单；调用成功/参数错误/handler 抛错三种结果；错误令牌被拒；`__aexit__` 后连接被拒；两个并发服务的令牌互不可用。
- **完成标准**：上述测试通过；一次真实 codex 调用（极小提示）成功调到一个工具并看到图片。
- **验证命令**：`make check`

### T3：`CodexRuntime` 主体（完成）

- **目标**：实现 `AgentRuntime`：一轮 = 一个 `codex exec --json` 子进程，产出现有的 `AgentEvent` 序列。
- **涉及文件**：`backend/src/studio/agent/codex_args.py`（新，纯函数：参数构造）、`codex_events.py`（新：JSONL → `AgentEvent`）、`codex_runtime.py`（新：进程、账本、`register_codex`）、`codex_env.py`（新：子进程环境）、`backend/src/studio/main.py`（注册）、`backend/tests/agent/test_codex_args.py`、`test_codex_events.py`、`test_codex_runtime.py`、`backend/tests/agent/fixtures/codex/*.jsonl`（从 spike 证据裁剪、去掉任何身份信息）、假 CLI 脚本 `backend/tests/agent/fixtures/fake_codex.py`。
- **接口与要点**：
  - 参数：新会话 `exec <通用参数> -m <model> -c developer_instructions=<系统提示> "<消息>"`；续会话 `exec <exec 级参数> resume <thread_id> <resume 级参数> "<消息>"`（参数位置见 codex.md「续会话」）；`-C <workdir>`；effort 映射到 `-c model_reasoning_effort="<low|medium|high>"`（T1 已实测）；图片写到 `<data_dir>/codex/tmp/<turn>/` 后用 `-i` 传入，轮末删除。
  - 事件映射：`agent_message` → `TextBlock`；`reasoning`（若有）→ `ThinkingBlock`；`command_execution`/`file_change`/`mcp_tool_call` 的 `item.started`/`item.completed` → `ToolCall`/`ToolResult`（步数由 TurnRunner 照常计数）；`collaboration.*` 等多 agent 调用 → 记 `notice` 并不执行额外处理（系统提示末尾追加"不要派生子 agent"）；`turn.started` 之前的 `item.completed(type=error)` 视为配置警告（记日志并产出一条提示事件，界面上可见，不失败；桌面版 CLI 升级后参数失效时靠它发现）；`error` 事件只记日志，以 `turn.failed`/退出码为准；`turn.completed` → `Usage` + `TurnEnd(completed)`。
  - 用量：`turn.completed.usage` 是会话累计值，按账本求差；没拿到 `turn.completed` 时标 `unsettled`，下一轮差值含残余并标 `includes_carryover`（与 `ClaudeRuntime._turn_cost` 同一语义）。`Usage.auth="login"`，成本按配置单价估算，没有单价则为空。
  - 系统提示变更：账本存建会话时系统提示的哈希；续会话时哈希不同 → 在本轮用户消息前加一段"阶段说明已更新"并附新提示全文，然后更新哈希。
  - 错误：未登录/401 的错误文本规整成"Codex 未登录或登录已失效，请在终端运行 codex login"；stderr 尾部打码后进 `TurnEnd.error`（去掉看起来像 token 的长串）。
  - 读 stdout 不受 asyncio 默认 64 KiB 行长限制（按块读再切行）。
  - 取消在 T4 做；本任务里取消令牌置位时先直接终止进程，T4 替换。
- **测试**：参数构造（新会话/续会话/换模型/有图片/effort）；回放 JSONL：最小一轮、多轮累计求差、`unsettled` 残余、模型不存在、401、配置警告、重连 `error` 后成功、多 agent 调用、MCP 工具调用带图片、超长单行；假 CLI：非零退出且无终止事件、stderr 打码；系统提示哈希变化时消息带变更说明。
- **完成标准**：上述测试通过；`fake`/Claude/OpenAI 的测试不变。
- **验证命令**：`make check`

### T4：取消与进程清理（待开始）

- **目标**：取消可靠、不留孤儿进程。
- **涉及文件**：`backend/src/studio/agent/codex_runtime.py`、`backend/src/studio/agent/codex_procs.py`（新：列出某进程的全部后代及其进程组）、`backend/tests/agent/test_codex_cancel.py`、`test_codex_procs.py`。
- **接口与要点**：
  - 取消令牌置位 → SIGINT（Windows 上用 `CTRL_BREAK_EVENT`，未实测，记入意外与发现）→ 宽限 15 秒 → 仍在运行则先记下后代进程组，再强杀 codex 与这些进程组。
  - 后代进程用标准库实现（解析 `ps -A -o pid=,ppid=,pgid=`；Windows 用 `taskkill /T /F`），不引入 `psutil`。
  - 开始前已取消 → 不启动进程，直接 `TurnEnd(cancelled)`（与 ClaudeRuntime 一致）。
  - 取消轮账本标 `unsettled`。
- **测试**：假 CLI（Python 脚本，起一个 `sleep` 子进程并放进独立进程组）：响应 SIGINT 的情况在宽限期内结束且子进程被它自己收掉；忽略 SIGINT 的情况被强杀且独立进程组的 `sleep` 也被清理；开始前已取消不启动进程。
- **完成标准**：上述测试通过；测试结束后没有残留 `sleep` 进程（测试里断言）。
- **验证命令**：`make check`

### T5：permission profile 与隔离（待开始）

- **目标**：模型执行的命令只能读写本轮工作区，读不到其他项目和凭据，默认断网。
- **涉及文件**：`backend/src/studio/agent/codex_sandbox.py`（新：生成 profile 的 `-c` 参数）、`backend/src/studio/agent/sandbox_paths.py`（拒读清单加 `~/.codex`，Claude/OpenAI 路径一并受益）、`backend/src/studio/agent/exec_policy.py`（`codex_sandbox_available(platform)`）、`codex_args.py`、`backend/tests/agent/test_codex_sandbox.py`、`backend/tests/smoke/test_smoke.py`、`docs/references/codex.md`。
- **接口与要点**：
  - profile：`extends=":workspace"`；拒读仓库根、`data_dir`、`sensitive_home_dirs()`；放回本轮工作区为可写；`:tmpdir`、`:slash_tmp` 只读；`default_permissions` 指向它；不传 `-s`。
  - 平台：macOS 视为有沙箱；其他平台视为没有，按 `exec_mode`：`disabled` → 本轮直接失败并说明要打开无隔离开关；`unsandboxed` → `-s danger-full-access`，写入靠轮末 guard 兜底。
  - `view_image` 直接测试：工作区里放一个指向拒读文件（测试专用的图片，放在拒读目录下）的符号链接，让模型"看一下工作区里这张图"——模型只看到工作区路径，借此测工具层面是否按真实路径拦截。拦截 → 写进 codex.md；不拦截 → 登记 tech-debt 并在本计划「意外与发现」说明风险。
- **测试**：profile 参数构造（路径转义、放回工作区、仓库根与工作区嵌套）；`exec_mode` 三种结果；冒烟 `codex_login_sandbox_read`（只输出 OK/DENIED，与 Claude 同名用例同构）。
- **完成标准**：单元测试通过；冒烟结果满足 AC4。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k codex_login_sandbox"`

### T6：模型配置、设置页与周边接入（待开始）

- **目标**：用户能在界面上建、测、用 `codex` 配置；周边功能对 `codex` 有明确行为。
- **涉及文件**：
  - 后端：`db/repo/profiles.py`（`USER_RUNTIMES`、登录模式校验、种子 `codex-login`）、`api/profiles.py`、`api/sessions.py`（换模型：同运行时同供应商即可）、`agent/oneshot.py`（`codex` 分支：`--ephemeral`，不带工具，复用参数构造）、`agent/probe.py`（`codex` 超时 120 秒，未安装的原因）、`agent/titler.py`（`SUPPORTED_RUNTIMES` 含 `codex`）、`agent/runner.py`（`_native_web_supported` 对 `codex` 返回假，联网阶段回退到自建联网工具）、`api/attachments.py`（`codex` 的附件说明：图片可用 `view_image` 看，二进制按 Shell 处理）及对应测试。
  - 前端：`features/settings/profileForm.ts`（`USER_RUNTIMES`、`codex` 必须留空 key）、`ModelProfileDialog.vue`（选 `codex` 时隐藏/禁用 key 输入并提示"使用本机 ChatGPT 登录"）、`ModelProfilesPanel.vue`（运行时标签）及 spec。
- **测试**：校验（`codex` + key → 422；`codex` 无 key → 通过）；种子幂等；oneshot/probe 的 `codex` 分支用假 CLI；titler 对 `codex` 会话调用 oneshot；附件说明文案；`profileForm.spec.ts`、`ModelProfilesPanel.spec.ts`。
- **完成标准**：上述测试通过；`make dev` 下设置页能看到 `codex-login` 并测试成功（截图留到 T7 一起做）。
- **验证命令**：`make check`

### T7：冒烟、文档与实测验收（待开始）

- **目标**：真实模型下跑通，文档和质量记录到位。
- **涉及文件**：`backend/tests/smoke/test_smoke.py`（`test_codex_login`、`test_codex_login_cancel_then_turn`、`test_codex_login_tools`，以及 T5 的 `test_codex_login_sandbox_read`；CLI 未安装或未登录时 skip 并说明原因）、`scripts/tasks.py`（冒烟白名单环境如需放行 `STUDIO_CODEX_BIN`）、`docs/references/codex.md`、`docs/runbooks/dev-setup.md`（安装与 `codex login`）、`docs/runbooks/verification.md`（codex 冒烟用法）、`docs/quality/QUALITY.md`、`docs/quality/tech-debt.md`（多 agent 工具、Windows 未测等）、`docs/plans/TODO.md`（Windows 实测）、`docs/ARCHITECTURE.md`（模块地图加 codex 相关模块）。
- **接口与要点**：
  - 冒烟版本漂移检查：`test_codex_login` 记录 `codex --version`，与 `codex_cli.VERIFIED_VERSION` 不同时在输出里提醒复验（不判失败：桌面版会自动更新）。
  - AC6、AC7 用 `make dev` + 浏览器实测并截图，填「验证记录」。
- **测试**：上述冒烟用例。
- **完成标准**：AC1–AC8 都有证据。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k codex_login"`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-13 — T1 — 改用桌面版 CLI（负责人决定）；`codex_cli.py`（定位、版本）、`STUDIO_CODEX_BIN`；思考强度实测通过（`r1g-*`）（03a10cf）
- 2026-10-13 — T2 — 实测选定方案 A（每轮内置 HTTP MCP）；`codex_mcp.TurnToolServer`；真实 codex 调到工具并看到图片（`r2a`–`r2d`）（9c1cbda）
- 2026-10-13 — T3 — `codex_args`/`codex_events`/`codex_env`/`codex_runtime`，`events.Notice`；真实 CLI 跑两轮（含业务工具、续会话、提示更新）通过

## 下一步

- 从 T4 开始：`CodexRuntime._stop_on_cancel` 目前直接 `proc.kill_tree`（T3 的临时做法），换成 SIGINT → 宽限 → 强杀并清理孤儿进程组。先写 `test_codex_cancel.py`（假 CLI 起一个独立进程组的 `sleep`），再实现 `codex_procs.py`。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-13 — T2 选方案 A（每轮内置 HTTP MCP 服务），不做 stdio 桥接 — 实测登录模式与 permission profile 下都可用，续会话换端口令牌也可用；不需要额外进程和回调通道，handler 直接拿本轮 `ToolContext`。
- 2026-10-13 — codex 侧 `required=true` — 不加时令牌或服务出错会被悄悄忽略，模型只是看不到工具；加了之后启动即失败（只有 stderr 有原因，T3 要把 stderr 尾部带进错误）。
- 2026-10-13 — `tool_timeout_sec=900` — 渲染预览、配乐合成要跑几分钟；900 秒高于工具自身最长的超时（Shell 上限 600 秒），超时由工具自己报，codex 这层只兜底。
- 2026-10-13 — T3：提示词改从 stdin 传（`-`），图片用 `--image=<路径>` — 系统提示与前言可能很长；`-i` 是可变参数，会吞掉位置参数（实测 `r3a`/`r3b`）。
- 2026-10-13 — T3：新增 `events.Notice(kind, message)`，TurnRunner 落库为 `notice` — 计划要求 codex 配置警告"界面上可见"，现有事件里没有运行时可用的提示类型；前端加 `runtime_warning` 的标签。
- 2026-10-13 — T3：只有 `turn.started` 之前的 `error` item 产出提示，之后的（WebSocket 回落 HTTPS 等传输层消息）只记日志 — 前者是配置问题，后者是噪音。
- 2026-10-13 — T3：子进程环境额外去掉 `STUDIO_` 前缀的变量，保留 `CODEX_HOME` — 前者是本应用的配置，与 codex 无关；后者决定去哪里读登录。
- 2026-10-13 — T3：账本没有提示摘要（例如老会话）时不发更新块，直接记下当前摘要 — 无从判断是否变过。
- 2026-10-13 — 参数校验只在 `invoke_tool` 做一次（MCP 层 `validate_input=False`），错误文案与其他运行时一致。

- 2026-10-13 — **CLI 改用 ChatGPT 桌面版自带的**（负责人决定，ADR 0030 前提 2 改定）— 计划原定在 `tools/codex/` 安装 `@openai/codex@0.162.1`；T1 开始安装时发现 npm 包解压约 340 MB（与桌面版自带的 322 MB 相当），下载约 8 分钟只下了 43 MB。改用桌面版后不再有 npm 新依赖，也不需要在新版本上复验（实测用的就是这个版本）；T1 缩为"定位 + 补测思考强度"。
- 2026-10-13 — `runtime=codex` 只允许登录模式 — `CODEX_API_KEY` 模式是付费调用，没有授权，也没有实测。
- 2026-10-13 — 联网阶段对 `codex` 不开 codex 自带的网页搜索，回退到自建联网工具（经 MCP）— 沙箱默认断网，自建工具在后端进程里运行，不受影响；与 OpenAI 非官方 provider 的处理一致。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 2026-10-13 — T3：续会话时把更新后的阶段说明放进用户消息，codex 收到了但模型不一定照做（说明改成"用法语回答"，模型仍用英文）。用户消息的优先级低于建会话时的 `developer_instructions`。机制保留（总比静默用旧提示好），已写进 codex.md；阶段说明大改时新建会话更可靠。

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 无
