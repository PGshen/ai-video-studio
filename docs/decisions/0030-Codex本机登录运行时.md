# 0030：用 ChatGPT 本机登录驱动 Codex 作为第三种运行时

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳（2026-10-13，负责人接受全部四条前提） |
| 日期 | 2026-10-13 |
| 相关 | [codex-login-spike 计划](../plans/completed/codex-login-spike.md)、[codex.md](../references/codex.md)、[ADR 0008](0008-模型接入方式.md)、[ADR 0009](0009-Shell沙箱.md)、[ADR 0012](0012-会话内同供应商换模型.md) |

## 背景

Claude 可以用本机订阅登录（`claude-login`，ADR 0008），不产生 API 费用；GPT 只能经 OpenAI Agents SDK 用 API key（目前走 OpenRouter）。负责人有 ChatGPT 订阅，问 GPT 能否也走本机登录。

ChatGPT 登录的 OAuth token 公开 API 不接受，把它挪给 Agents SDK 属于非官方用法，不考虑。官方支持这份登录的只有 Codex：它和 Claude Code 一样，是自带 agent 循环、命令工具和沙箱的本地 CLI。spike（2026-10-13，ChatGPT 桌面版自带的 `codex-cli 0.162.0-alpha.17.2`）实测了能否把它接成本项目的运行时，结论见 [codex.md](../references/codex.md)。

## 决定

**有条件做。** 技术上可行，本项目需要的能力都有对应手段；正式接入前需要负责人对下面「前提」逐条拍板。

接入形态（供正式计划使用）：

- **运行时**：新增 `runtime=codex`。每轮以子进程启动 `codex exec --json`，后续轮用 `exec ... resume <thread_id>`；`thread_id` 存为 `sdk_ref`。不引入 Python SDK（PyPI 上的 `openai-codex-sdk` 来源未核实），自己解析 JSONL 事件。
- **认证**：模型配置 `api_key_env` 为空即登录模式，与 `claude-login` 一致；子进程环境置空 `CODEX_API_KEY`（它会覆盖登录）及其他 `OPENAI_*`/密钥类变量；`CODEX_HOME` 保持默认（复制凭据会让 refresh token 互相作废）。会话文件落在 `~/.codex/sessions/`。
- **上下文收口**：固定加 `--ignore-user-config` 与 references 中的最小上下文参数组合（关闭仓库 `AGENTS.md`、用户 skills、插件、记忆、网页搜索等）；阶段系统提示经 `developer_instructions` 注入。它只在建会话时生效，所以 codex 会话与阶段一一对应。
- **业务工具**：经 MCP 提供，服务器配置 `default_tools_approval_mode="approve"`（否则直接失败），用 `enabled_tools` 做阶段白名单。stdio 桥接进程和后端直接提供 HTTP MCP 端点两种形态，在正式计划的第一个任务里实测后选定。
- **沙箱**：用 `-c` 定义 permission profile（`extends=":workspace"`，拒读仓库根、`data_dir`、凭据目录，放回当前工作区为可写，`:tmpdir`/`:slash_tmp` 只读），不传 `-s`。拒读路径复用 `agent/sandbox_paths.py`。默认断网；需要联网的阶段另议。profile 只约束模型执行的命令，MCP 子进程不受约束（实测）；`view_image` 等进程内读文件工具是否受拒读约束无法经由模型验证，正式计划要补一个直接的测试。
- **取消**：先发 SIGINT（codex 会收掉自己启动的命令进程），宽限后再强杀；codex 把命令放在独立进程组，强杀会留下孤儿，需要兜底清理。
- **用量**：`turn.completed.usage` 是会话累计 token，按差值记本轮；没有成本字段，登录模式只记 token。取消轮的消耗计入下一轮累计值，沿用 ClaudeRuntime 的 `unsettled` 处理。

前提（2026-10-13 负责人已全部接受）：

1. **合规**：第三方工具使用 ChatGPT 登录是否可接受，由负责人判断（同 ADR 0008）。
2. **CLI 来源与版本**（2026-10-13 负责人决定：**用 ChatGPT 桌面版自带的 CLI**。起初定为单独安装固定版本的 `@openai/codex`，开始安装后发现 npm 包解压约 340 MB、与桌面版自带的 322 MB 相当且下载很慢，改回桌面版）：实测用的就是桌面版自带的 alpha 版 CLI，它随桌面版自动更新；不少配置键是从二进制字符串里找到的，并没有官方文档。兜底：运行时把 codex 的配置警告（未识别的键等）记进日志并提示；`make smoke` 的 codex 用例对比实测版本，版本变了就提醒复验；`STUDIO_CODEX_BIN` 可以改用别的 CLI（Windows，或需要锁定版本时）。
3. **体验差异**：单轮最小请求 28–44 秒，约为 Claude 本机登录的 2–3 倍；多 agent 工具（`collaboration.*`）关不掉（`--disable multi_agent` 只额外加了一段“不要主动派生子 agent”的说明），只能在提示里禁止，并在事件流里检测。
4. **Windows**：没有实测；permission profile 在 Windows 上的效果未知，按 [ADR 0024](0024-无隔离执行开关.md) 的无隔离开关处理。

## 考虑过的其他方案

- **把 ChatGPT OAuth token 交给 OpenAI Agents SDK**：调用非公开端点，随时可能失效，违反服务条款的风险也最高。不选。
- **只保留 API key 路径**（OpenRouter）：不用做任何事，但 GPT 一直要付费。如果负责人不需要用订阅额度跑 GPT，就选这个。
- **用 `codex app-server`（JSON-RPC）代替 `codex exec --json`**：能力更全（审批回调、动态工具），但协议更复杂，spike 没有实测；`exec` 已经能满足需求。

## 影响

- 好处：GPT 模型可以用订阅额度运行，真实模型测试多了一条免费路径。
- 代价：第三套事件映射和取消逻辑；依赖一个随桌面版自动更新的 alpha CLI；会话文件会混进 `~/.codex/sessions/`，和负责人自己使用 Codex 的会话放在一起。
- 正式计划的粗分：① MCP 桥接形态实测与实现；② `CodexRuntime`（启动、事件映射、续会话、累计用量）；③ 取消与进程清理；④ permission profile 生成与隔离测试；⑤ 模型配置 `runtime=codex`、设置页、连通性测试；⑥ 冒烟用例与文档。规模与 M1x 级别的计划相当。
