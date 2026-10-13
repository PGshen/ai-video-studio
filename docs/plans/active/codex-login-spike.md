# codex-login-spike：用 ChatGPT 本机登录驱动 Codex 的可行性实测

<!-- 本计划是 spike：只做实测与结论，不改产品代码。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 运行时扩展预研（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [架构设计](../../design/2026-09-26-architecture.md)（运行时抽象 `AgentRuntime`）；[ADR 0008](../../decisions/0008-模型接入方式.md)（Claude 本机登录先例）；[claude-agent-sdk.md](../../references/claude-agent-sdk.md)（登录模式的实测方法） |
| 分支 | `codex-login-spike`（开工时从 main 切出） |
| 批准记录 | 2026-10-13：负责人批准计划，选择 Native 执行（本会话内执行） |

## 目标

回答一个问题：**能不能像 `claude-login` 那样，用本机 ChatGPT 订阅登录驱动 Codex，作为本项目的第三种运行时（`runtime=codex`）？** 产出是一份经过实测的 `docs/references/codex.md`、一份 ADR 草稿（提议状态），以及“做 / 不做”的结论和正式接入计划的范围估计。本计划不写任何产品代码。

## 背景（已知事实，2026-10-13 核实）

- 本机 `~/.codex/auth.json` 的 `auth_mode` 为 `chatgpt`（由 ChatGPT 桌面版写入）；PATH 上没有 `codex`，但 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` 存在，版本 `codex-cli 0.162.0-alpha.17.2`。npm 上 `@openai/codex` 最新稳定版为 `0.162.1`。
- 现有 openai 运行时（OpenAI Agents SDK）只能用 API key 调公开 API；ChatGPT 登录的 OAuth token 公开 API 不接受，不在本计划考虑范围内（不做 token 挪用）。
- Codex 与 Claude Code 同形态：本地 CLI 自带 agent 循环、命令/补丁工具和沙箱；`codex exec --json` 输出 JSONL 事件，`codex exec resume` 续会话。第三方资料称认证优先级为 `CODEX_API_KEY` → `auth.json` 中的 API key → ChatGPT OAuth（`CODEX_HOME`，默认 `~/.codex`），**未经本项目实测**。
- PyPI 上有 `openai-codex-sdk 0.1.11`，元数据作者写 OpenAI 但没有项目链接，来源未核实；本 spike 不安装它，直接以子进程调 CLI。

## 范围

**包含：**

- 用本机 ChatGPT 登录跑 `codex exec --json`，记录认证、模型、事件格式、续会话、取消、用量。
- 业务工具经 MCP（stdio）提供给 Codex 的可行性，含图片结果。
- 沙箱与权限：只写工作区、断网、能否拒读仓库根与 `data_dir`、能否关闭不需要的内置工具。
- 结论文档：`docs/references/codex.md`、ADR 草稿、TODO 条目。

**不包含：**

- `CodexRuntime` 的实现、模型配置新增 `runtime=codex`、前端改动（属于后续正式计划，视结论而定）。
- 安装 npm 或 PyPI 上的 Codex 包；改动 `~/.codex/config.toml` 或 `~/.codex/auth.json`（只读）。
- API key 模式的 Codex 实测（会产生费用）。
- Windows 上的实测。

## 全局约束

- **不改产品代码**：`backend/src`、`frontend/src` 无改动；`make check` 保持绿。
- **不引入依赖**：用 ChatGPT.app 自带的 `codex` 二进制，路径通过环境变量 `STUDIO_CODEX_BIN` 传给探针脚本，不写死。
- **探针脚本不入库**：放在 `data/evidence/codex-spike/probes/`，证据（JSONL、日志）放在 `data/evidence/codex-spike/`，与以往 spike 一致；结论、命令和证据路径写进 references。
- **凭据只读**：任何时候不打印 `auth.json` 的 token；探针启动 codex 时置空继承来的 `OPENAI_API_KEY`、`CODEX_API_KEY`、`OPENAI_BASE_URL` 等变量（`backend/.env` 里的 OpenRouter key 不能被 Codex 误用）。
- **真实调用授权**：本计划批准即视为预先同意用本机 ChatGPT 订阅登录跑真实模型（走订阅额度，不产生 API 费用，不限次数；对应 SOP §6 第 7 条）。任何 API key 付费调用不在授权范围内。
- 工作区用临时目录（`data/evidence/codex-spike/ws-*`），不碰真实项目数据；不在工作区里用 git（Codex 默认要求 git 仓库，需用 `--skip-git-repo-check`，这一点本身要记录）。
- 第三方产品使用 ChatGPT 登录是否合规，由负责人自行判断（同 ADR 0008 对 Claude 登录的处理），ADR 草稿里写明。

## 验收标准

- [ ] AC1：一轮最小对话在 ChatGPT 登录下完成，记录：认证来源确认（置空 key 后仍成功）、实际模型名、可用的 `-m` 取值、JSONL 事件类型清单（含用量字段）、单轮耗时。（验证方式：T1 证据 + references 表格）
- [ ] AC2：`CODEX_HOME` 指向独立目录时登录凭据是否仍可用、会话文件落在哪里——结论明确（对应 Claude 侧 `CLAUDE_CONFIG_DIR` 的坑）。（验证方式：T1 对照实验）
- [ ] AC3：续会话（`exec resume`）第二轮能复述第一轮内容；中途 SIGINT/SIGTERM 后进程与子进程退出、下一轮能续上；用量是否累计、取消轮的用量是否丢失——结论明确。（验证方式：T2 证据）
- [ ] AC4：一个 stdio MCP server 提供的业务工具被模型调用，文本结果和图片结果都被模型“看到”（图片用左蓝右黄的 PNG，文字不提颜色）；能否只开放指定工具、关闭原生 web search。（验证方式：T3 证据）
- [ ] AC5：沙箱结论：`workspace-write` + 断网下，工作区内可写、工作区外写被拒、联网被拒；**读**仓库根、`backend/.env`、`data/` 下其他目录、`~/.ssh` 的结果，以及有无办法拒读（配置项或外包一层 `sandbox-exec`）。`approval_policy=never` 时不出现交互阻塞。（验证方式：T4 证据）
- [ ] AC6：`docs/references/codex.md` 按 references 现有格式（状态 / 结论 / 来源）记录以上全部结论；ADR 草稿（提议）给出“做 / 不做 / 有条件做”与理由；`docs/plans/TODO.md` 增加正式接入的条目（含范围估计）或不做的说明。（验证方式：文档检查，`make check` 绿）

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：认证、最小一轮与事件格式（完成）

- **目标**：确认 ChatGPT 登录能被子进程方式的 `codex exec` 使用，拿到事件格式的第一手样本。
- **涉及文件**：`data/evidence/codex-spike/probes/run_exec.py`（不入库）、证据 `data/evidence/codex-spike/t1-*.jsonl`。
- **要点**：
  - 探针：以 `asyncio.create_subprocess_exec` 启动 `$STUDIO_CODEX_BIN exec --json --skip-git-repo-check -C <临时工作区> [-m <模型>] "<提示>"`，环境变量白名单化（置空 key 类变量），逐行收 JSONL 原样存证。
  - 实验：① 默认模型回复 `ok`；② 指定 2–3 个模型名（含不存在的名字，看错误形态）；③ 设 `CODEX_HOME=<临时目录>` 对照（预期读不到登录——确认失败形态，以及能否只复制 `auth.json` 解决；复制前停下来问负责人，因为涉及凭据文件拷贝）；④ 在环境里放一个假的 `OPENAI_API_KEY`，看是否覆盖登录（确认置空的必要性）。
  - 记录事件类型（线程开始、轮开始/结束、条目开始/更新/完成、错误等实际名字）和用量字段；有没有成本字段。
- **完成标准**：AC1、AC2 的结论写进 `codex.md` 草稿表格。
- **验证命令**：`make check`

### T2：续会话、取消与用量（完成）

- **目标**：确认多轮会话和取消语义能映射到本项目的轮次模型（`runner` 的取消令牌、宽限、`unsettled` 账本）。
- **涉及文件**：`probes/run_resume.py`、`probes/run_cancel.py`（不入库）；证据 `t2-*.jsonl`。
- **要点**：
  - 第一轮给一个背景事实，第二轮 `exec resume <thread_id>` 让它复述；记录 thread id 从哪个事件取得、会话文件位置。
  - 取消：让模型执行 `sleep 30`，在工具执行中发 SIGINT，再试 SIGTERM，最后 kill 进程组；看是否还有收尾事件、子进程是否残留、下一轮能否续上。
  - 用量：两轮各自的 token 数是本轮值还是累计值；被取消那一轮的用量是否出现在后续事件里。
  - 同一会话中途换模型（`-m`）能否续上（对应 ADR 0012）。
- **完成标准**：AC3 的结论写进 `codex.md`。
- **验证命令**：`make check`

### T3：业务工具经 MCP（待开始）

- **目标**：确认本项目的 `ToolSpec` 能以 stdio MCP server 的形式给 Codex 用。这是接入成本最大的差异：Claude 路径是 SDK 进程内 MCP，Codex 需要独立进程（或 HTTP MCP）。
- **涉及文件**：`probes/mcp_server.py`（不入库，用仓库已有依赖实现最小 stdio MCP server：一个返回文本的工具、一个返回 PNG 图片的工具）、`probes/run_mcp.py`。
- **要点**：
  - 先确认仓库现有依赖里有可用的 MCP server 实现（`claude-agent-sdk` 依赖链中的 `mcp` 包）；没有就停下来（不新增依赖），记进「阻塞」。
  - MCP server 通过 `-c mcp_servers.<名字>.command=...` / `args` / `env` 传入，不改 `~/.codex/config.toml`。
  - 记录：工具名在事件里的形态、调用参数与结果的事件格式、图片是否被模型看到、工具超时配置。
  - 工具收口：能否只开放指定 MCP 工具；能否关闭原生 web search、命令执行、补丁工具中的某些（对应各阶段的工具白名单）。
  - 业务工具需要访问后端状态（项目、快照等）：记录“独立进程 MCP 回调后端 HTTP” 这一形态需要什么（鉴权、端口），只做方案描述，不实现。
- **完成标准**：AC4 的结论写进 `codex.md`。
- **验证命令**：`make check`

### T4：沙箱与权限（待开始）

- **目标**：确认 Codex 自带沙箱能否满足本项目的隔离要求（设计 §4.1、ADR 0009：只写工作区、无外网、拒读仓库与 `data_dir`、拒读凭据目录）。
- **涉及文件**：`probes/run_sandbox.py`（不入库）；证据 `t4-*.jsonl`。
- **要点**：
  - `--sandbox workspace-write`、`-c sandbox_workspace_write.network_access=false`、`approval_policy=never`（实际参数名以 `codex exec --help` 和实测为准，写进 references）。
  - 让模型逐项执行：工作区内写文件；写 `$TMPDIR` 和仓库 `data/`；`cat backend/.env`；读 `data/` 下另一个临时目录；读 `~/.ssh` 下的文件名列表（只列不读内容）；`curl https://example.com`。
  - 提示词要说明来源（“这是本仓库作者授权的隔离测试”），并放进任务化指令里，避免像 Claude 登录冒烟那样被模型当作提示注入拒绝（见 TODO P2 条目）。
  - 预期 Codex 默认不拒读：评估两条补救路线并各做一次最小实测——① Codex 配置项（若存在）；② 用本项目 `shell_sandbox.seatbelt_profile` 生成的配置外包 `sandbox-exec` 启动整个 codex 进程（注意 codex 自身也要用 Seatbelt，嵌套是否被允许要实测）。
  - 轮末 guard（还原阶段可写范围之外的改动）与运行时无关，只需确认 Codex 写文件后 guard 能看到，不需要实测。
- **完成标准**：AC5 的结论写进 `codex.md`。
- **验证命令**：`make check`

### T5：结论与交接（待开始）

- **目标**：把实测结论变成可决策的文档。
- **涉及文件**：`docs/references/codex.md`（新建，入库）、`docs/references/README.md`（加索引）、`docs/decisions/0030-<标题>.md`（提议状态）、`docs/plans/TODO.md`。
- **要点**：
  - `codex.md`：版本与二进制位置、认证、事件格式、续会话与取消、用量、MCP、沙箱，每条带日期、状态（✅/⚠️）和证据路径。
  - ADR 草稿列出：选择（做 / 不做 / 有条件做）、接入形态（子进程 + JSONL 自己解析，还是采用某个 SDK）、必须的隔离补救、与 `claude-login` 对齐的配置方式（模型配置 `runtime=codex`、`api_key_env` 为空即登录模式）、合规说明由负责人判断。
  - TODO：结论为做时，写正式计划的任务粗分（`CodexRuntime`、事件映射、MCP 桥、沙箱、设置页、冒烟）和估计规模。
- **完成标准**：AC6；负责人审阅结论。
- **验证命令**：`make check`

## 进度

- 2026-10-13 — T1 — 完成：登录可用、事件格式、模型、`CODEX_HOME`/key 覆盖对照、注入上下文收口；结论写进 `references/codex.md`
- 2026-10-13 — T2 — 完成：`resume` 可续、换模型可续；用量是会话累计值；取消须用 SIGINT（TERM/KILL 留孤儿命令进程）；取消轮用量计入下一轮累计值

## 下一步

- 做 T3：写 `data/evidence/codex-spike/probes/mcp_server.py`（先确认 `backend/.venv` 里有 `mcp` 包，用 `backend/.venv/bin/python` 运行它），用 `-c 'mcp_servers.studio.command="..."'`、`-c 'mcp_servers.studio.args=[...]'` 传入；探针参数用 `source probes/min.zsh` 得到的 `$M` 数组。同时试关掉 `collaboration.*`/`request_user_input` 工具（二进制里有 `ToolsToml`、`enabled_tools`），以及续会话时 `developer_instructions` 是否重复注入。

## 决策记录

- 2026-10-13 — Ruling：不复制 `auth.json` 到独立 `CODEX_HOME`，登录模式沿用 `~/.codex`（会话落在 `~/.codex/sessions/`）— 与 Claude 登录模式会话落在 `~/.claude/projects/` 的先例一致；复制 OAuth 凭据会让两份 refresh token 互相作废（轮换），还会扩大凭据副本面 — 如果判断错：正式运行时需要另找隔离会话文件的办法（例如定期清理或 `--ephemeral` 加自建历史）。
- 2026-10-13 — spike 直接以子进程调用 ChatGPT.app 自带的 `codex`，不安装 `@openai/codex` 或 `openai-codex-sdk` — 不引入计划外依赖；`openai-codex-sdk` 来源未核实。

## 意外与发现

- 2026-10-13 — T2：codex 把模型执行的命令放在独立进程组里，SIGTERM/SIGKILL 取消会留下孤儿进程（实验后已手动清理）。正式运行时取消必须先发 SIGINT 等它收尾，超时再强杀，并且要另想办法兜底清理命令进程（例如记录 `command_execution` 的进程或外包一层沙箱进程）。
- 2026-10-13 — 即使 `--ignore-user-config`，Codex 仍会注入仓库根的 `AGENTS.md`（从工作区往上找）、用户级 skills 列表（含开发用的 superpowers）、多 agent 角色段。前两项可用 `-c` 关闭；多 agent 段和 `collaboration.*` 工具用 feature 开关关不掉，留到 T3 继续找办法。详见 `references/codex.md`。
- 2026-10-13 — `CODEX_API_KEY` 会覆盖登录，`OPENAI_API_KEY` 不会；无凭据时要重试约 75–85 秒才失败，正式运行时需要自己的超时。
- 2026-10-13 — 单轮最小请求 28–44 秒，明显慢于 Claude 本机登录（12–14 秒）；stderr 经常有刷新模型列表超时。

## 阻塞

- 无

## 验证记录

- 无
