# M1x：M2 前的技术债清理

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | M1 与 M2 之间（整理） |
| 设计依据 | [架构设计 §4.3、§4.4](../../design/2026-09-26-architecture.md)；登记表 [tech-debt.md](../../quality/tech-debt.md) |
| 分支 | `m1x-tech-debt` |
| 批准记录 | 2026-09-28：负责人选定范围「小修 + 结构拆分」、TD-20 用 sandbox-exec、TD-1 用 denyRead + 联网默认关；2026-09-28：负责人批准计划，执行方式 Subagent-driven |

## 目标

在 M2 大量改动 `agent/runner.py` 和两个运行时之前，先把 M1 登记的技术债中**会随 M2 放大**的部分处理掉：修掉已知的小缺陷、把过大的文件拆开、收紧两条运行时路径的本机文件读取与外发风险。完成后 agent 行为对用户不变（除了选题阶段暂时不联网），`make check` 为绿，M2 可以在更小、更清楚的模块上开工。

## 范围

**包含（按登记号）：**

- 小修：TD-2、TD-3、TD-4、TD-5、TD-7、TD-8、TD-12、TD-13、TD-14（仅"显式取消 reader"部分）
- 成本统计：TD-11
- 测试放松：TD-10（放在结构拆分之前，让拆分不被精确事件顺序绑住）
- 结构：TD-15、TD-16、TD-17、TD-18
- 安全：TD-1（sandbox `filesystem.denyRead` + 选题阶段 `allow_web` 暂时关闭，M4 再开）、TD-20（OpenAI 路径 Shell 用 macOS `sandbox-exec` 包裹；非 macOS 不提供 Shell）

**不包含（继续登记，写明去向）：**

- TD-6、TD-9：上游/用户修改的判定口径，和 M3 的按镜头摘要一起改。
- TD-19：排队消息重发，属于交互功能，M5。
- TD-21：M2 落地 `render_preview` 时处理。
- TD-22、TD-23、TD-24：目前没有实际痛点，出现症状时再处理。
- TD-14 的 `setsid` 逃逸：sandbox 之后危害降为"后台进程在轮末之后改工作区"，保留登记。

## 评审关注点

1. **拆分后行为漂移**：runner/运行时拆模块后，事件持久化、SSE 推送、快照、guard 的时序必须与拆分前一致 → T4 先把测试改成断言相对顺序和不变量，T6/T7 拆分时这些测试不改一行。
2. **denyRead 误伤**：拒读仓库和 `data/` 之后，Bash 仍须能读当前工作区（含 `upstream/`）以及系统路径（`/usr`、`/bin`、Python/Node 运行时）→ T8 真实冒烟覆盖"读工作区成功、读 `backend/.env` 失败"。
3. **sandbox-exec 误伤**：Shell 在沙箱里仍须能跑 `python3`、`ls`、`cat` 工作区文件、写 `$TMPDIR` 以外的工作区路径 → T9 在本机真实执行测试。
4. **重启恢复时误还原用户改动**：TD-7 的恢复 guard 只能按可写范围还原，不能动可写范围内的文件 → T2 测试覆盖。
5. **取消与成本**：强制取消的那一轮花费不能计入下一轮，也不能丢；`max_cost_per_turn=0` 不应启动模型 → T3 测试覆盖。

## 依赖清单

不引入新依赖。`sandbox-exec` 是 macOS 系统自带命令（`/usr/bin/sandbox-exec`）。

## 真实模型测试

T3、T8 需要真实 Claude 调用，按 SOP §6 第 7 条例外，用本机登录的订阅账号（`make smoke SMOKE_ARGS="-k claude_login"`），不限次数。T9 的 OpenAI 真实 Shell 冒烟需要 `OPENAI_API_KEY` 官方地址；**不在本计划预授权内**，默认只做本机 `sandbox-exec` 的真实执行测试（不经模型），真实模型冒烟需要时再问负责人。

## 验收标准

- [ ] AC1：`make check` 为绿；登记表中范围内的 16 项移到「已处理」，不处理的项写明去向。（验证：`make check` 输出、tech-debt.md diff）
- [ ] AC2：`agent/runner.py`、`agent/openai_runtime.py`、`agent/claude_runtime.py` 各自 ≤ 400 行；`ToolContext` 只在一处构造；步数预算只有 runner 一处口径。（验证：`wc -l`、`grep -rn "ToolContext(" backend/src`）
- [ ] AC3：Claude 路径 Bash 读 `backend/.env` 被拒、读工作区文件成功；选题阶段不再提供 WebSearch/WebFetch。（验证：本机登录冒烟日志存入 `data/evidence/m1x/`）
- [ ] AC4：OpenAI 路径 Shell 在 macOS 上经 `sandbox-exec` 执行：读仓库 `backend/.env` 失败、写工作区外失败、无外网，读写工作区成功；非 macOS 不提供 `ShellTool`。（验证：`tests/agent/test_shell_sandbox.py` 在本机真实执行的输出）
- [ ] AC5：浏览器里用 Fake 跑一轮，时间线、画布刷新、快照与拆分前一致。（验证：L4 截图）
- [ ] AC6：ADR 0009（Shell 沙箱策略）已写；references 两篇补充实测结论；QUALITY.md、ARCHITECTURE.md 更新。

## 任务

### T1：配置与 workspace 小修（TD-2、TD-3、TD-4、TD-5）（待开始）

- **目标**：端口配置真正生效；测试不再依赖私有常量；快照少读一遍文件；workspace 层统一过滤排除目录；guard 不留空目录。
- **涉及文件**：`scripts/dev.sh`、`backend/src/studio/config.py`、`backend/tests/test_config.py`、`backend/src/studio/workspace/{snapshot,files,scope}.py`、`backend/src/studio/api/files.py`、对应测试。
- **接口与要点**：
  - TD-2：`dev.sh` 用 `uv run python -m studio.config`（新增 `__main__` 块，输出 `host port` 两个值）取绑定地址，传给 uvicorn；保留 `Settings.host/port`。
  - TD-3：`config.py` 提供公开的 `repo_root() -> Path`（或改测试只断言行为：默认 `data_dir` 的名字与相对位置、源码目录内的路径被拒），测试不再 import 下划线常量。
  - TD-4：`scan` 返回 `(manifest, 内容缓存或 sha→path)`，`create_snapshot` 对已存在于 blob 库的 sha 不再读文件，新 blob 只读一次。
  - TD-5：`list_tree`/`read_text` 默认排除 `EXCLUDED_TOP_DIRS - {"upstream"}`（与 `api/files.py:_HIDDEN_TOP_DIRS` 同口径，把常量下沉到 `workspace.layout`，api 层改用它）；`guard` 还原后调用 `_prune_empty_dirs`。
- **测试**：新端口经 `STUDIO_PORT` 生效（测 `__main__` 输出）；快照对已存在 blob 不重复读（用计数的文件读替身或 monkeypatch `Path.read_bytes`）；`list_tree` 不含 `.cache/`、`output/`；越界新建 `a/b/c.txt` 被 guard 还原后 `a/` 不存在。
- **完成标准**：上述测试先红后绿；`make check` 绿。
- **验证命令**：`make check`

### T2：runner 小修（TD-7、TD-8、TD-13）（待开始）

- **目标**：Claude 原生写工具的改动路径能推送；路径不重复；嵌套参数也截断；重启恢复时做一次越界还原。
- **涉及文件**：`backend/src/studio/agent/runner.py`、`backend/tests/agent/test_runner.py`。
- **接口与要点**：
  - TD-13/TD-8：`_after_tool_result` 从 `path`、`file_path`、`notebook_path`、`move_to` 取候选，与 recorded 合并后按出现顺序去重。
  - TD-8：`_truncate_args` 递归处理 dict/list 中的字符串。
  - TD-7：`_recover_turn` 对 `running` 的 turn 先按该阶段的 `write_scope` 做一次 `guard(tool_writes=空)`，再做 `partial` 快照；guard 基线为该 turn 的起始快照。guard 失败只记日志，不阻止恢复。
- **测试**：`file_path` 参数产生的 `workspace_changed.paths` 非空；同一路径只出现一次；三层嵌套的超长字符串被截断；恢复时越界文件被还原、可写范围内的改动保留并进入 partial 快照。
- **完成标准**：测试先红后绿；`make check` 绿。
- **验证命令**：`make check`

### T3：Claude 运行时的取消与成本口径（TD-11、TD-12）（待开始）

- **目标**：取消能在 connect 阶段立即生效；0 预算直接拒绝；成本账本读写用同一个 SDK 会话 id；强制取消后本轮花费不计入下一轮。
- **涉及文件**：`backend/src/studio/agent/claude_runtime.py`、`backend/tests/agent/test_claude_runtime.py`、`docs/references/claude-agent-sdk.md`。
- **接口与要点**：
  - TD-12：`run_turn` 在 connect 前、connect 后检查 `cancel_token`，已取消直接 `TurnEnd(status="cancelled")`；`max_cost_per_turn == 0` 时不连 SDK，返回 `budget_exceeded`。
  - TD-11：账本键统一为 `ResultMessage.session_id`（读取时用 `ctx.resume_ref`，二者在 resume 场景相同，差异场景写测试固定行为）；取消时若拿到了 result 仍记录累计值；拿不到 result 时在账本里记"待校准"，下一轮以 `cumulative − 上次已知累计` 计算并在 `Usage` 上标注含上一轮残余（字段名在实现时定，写入决策记录）。
- **测试**：mock SDK 覆盖 connect 前取消、connect 中取消、0 预算、取消后下一轮成本不重复计入。
- **真实验证**：本机登录冒烟跑一次"中途取消 + 再发一轮"，把两轮 `cost_usd` 与 transcript 累计值对照写进 references。
- **完成标准**：测试绿；references 补一行实测结论。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`

### T4：完整一轮测试改为断言相对顺序（TD-10）（待开始）

- **目标**：runner 调整事件顺序时不必同步改大量断言。
- **涉及文件**：`backend/tests/api/test_stream.py`、`backend/tests/agent/test_runner.py`，可在 `backend/tests/` 下新增断言辅助函数。
- **接口与要点**：辅助函数 `assert_in_order(events, *types)`（子序列判断）和按类型分组计数；保留真正的不变量：`turn_start` 最先、`turn_end` 最后、`workspace_changed` 在对应 `tool_result` 之后、快照事件在 `turn_end` 之前。
- **测试**：本任务只改测试；先故意在本地交换两个无关事件的顺序确认新断言不红（不提交），再恢复。
- **完成标准**：测试语义不减弱（每条原断言都能在新写法里找到对应的不变量，列在 commit 说明里）；`make check` 绿。
- **验证命令**：`make check`

### T5：`TurnContext.tool_context()` 与单一步数口径（TD-17、TD-18）（待开始）

- **目标**：`ToolContext` 只构造一处；步数预算以 runner 为准。
- **涉及文件**：`backend/src/studio/agent/{runtime,fake,claude_runtime,openai_runtime,runner}.py`、对应测试。
- **接口与要点**：
  - `TurnContext.tool_context(self) -> ToolContext`；三个运行时改用它。
  - 步数：runner 在收到 `ToolCall` 时计数并在超限时 `_exceed_budget("steps")`（已有），运行时里的计数删除；Claude 运行时不再自行 interrupt，改由 runner 的取消令牌触发（行为：超限后本轮以 `budget_exceeded` 结束，与现在一致）。OpenAI 运行时如有 `max_turns` 之类 SDK 参数，只作为 `max_steps` 的宽松兜底（例如 `max_steps * 2`），写入决策记录。
- **测试**：新增 `test_tool_context_matches_turn_context`；已有的步数超限测试移到 runner 层，运行时层改为"收到取消令牌后结束"。
- **完成标准**：`grep -rn "ToolContext(" backend/src` 只剩 `runtime.py` 一处（`tools.py` 定义除外）；`make check` 绿。
- **验证命令**：`make check`

### T6：拆出 Shell executor（TD-16、TD-14 reader 部分）（待开始）

- **目标**：`openai_runtime.py` 降到 400 行以内；取消时 reader 任务被显式取消并等待结束。
- **涉及文件**：新建 `backend/src/studio/agent/shell.py`（`LocalShellExecutor`、`_read_capped`、`_wait_for_exit`、`_kill_group`、`_shell_env`、常量）；必要时再拆 `agent/openai_tools.py`（`build_function_tool`、`_sdk_output`、`_tool_call`/`_tool_result` 转换）；`backend/tests/agent/test_shell.py`（从现有测试迁出）；import-linter 契约与 ARCHITECTURE.md 同步。
- **接口与要点**：`LocalShellExecutor` 公开签名不变；取消路径改为 `cancel` 后 `await asyncio.gather(*readers, return_exceptions=True)`（带超时）。
- **测试**：迁移后的 shell 测试不改断言；新增"取消后没有未完成的 reader 任务"测试（检查 `asyncio.all_tasks()`）。
- **完成标准**：`wc -l agent/openai_runtime.py` ≤ 400；`make check` 绿。
- **验证命令**：`make check`

### T7：拆分 TurnRunner（TD-15）（待开始）

- **目标**：`runner.py` ≤ 400 行，M2 加 worker/渲染相关逻辑时有清楚的落点。
- **涉及文件**：`backend/src/studio/agent/runner.py` 拆为 `runner.py`（公开接口 `TurnRunner`、调度与排队）、`turn_events.py`（`_handle`/`_after_tool_result`/截断/持久化与推送）、`turn_finish.py`（`_finish`、guard、快照、`_finish_turn_row`）、`recovery.py`（`recover_on_startup`）；ARCHITECTURE.md 与 import-linter 同步。
- **接口与要点**：`TurnRunner` 的公开方法与异常类（`SessionBusyError`、`SessionNotFoundError`）不变、仍从 `studio.agent.runner` 导出；`_Job`/`_State` 放到内部模块共享。纯搬移，不改逻辑；如确需改逻辑单独 commit。
- **测试**：不改现有测试断言（T4 之后的版本）；只调整 import。
- **完成标准**：`wc -l` 满足；`make check` 绿。
- **验证命令**：`make check`

### T8：Claude 路径拒读与选题阶段关联网（TD-1）（待开始）

- **目标**：Bash 读不到仓库和其他项目工作区；在联网能力有域名策略之前，所有阶段都不开联网。
- **涉及文件**：`backend/src/studio/agent/claude_runtime.py`（`SANDBOX` 改为按 `ctx.workdir` 生成的函数）、`backend/src/studio/stages/topic/__init__.py`、对应测试、`backend/tests/smoke/`、`docs/references/claude-agent-sdk.md`。
- **接口与要点**：
  - `sandbox_settings(workdir: Path, repo_root: Path, data_dir: Path) -> SandboxSettings`：`filesystem.denyRead` 包含仓库根目录和 `data_dir`，`filesystem.allowRead`（若 CLI 支持）放回当前 `workdir`。**先实测** CLI 的 denyRead/allowRead 优先级：若 deny 父目录后无法 allow 子目录，改为逐项列出需要拒读的兄弟路径（仓库下除 `data/` 外的顶层项、`data/` 下除当前项目外的项目目录、`data/*.db`），结论写进 references。
  - `SandboxSettings` 是 TypedDict，`filesystem` 字段若不在类型里，按 references 记录的"合并进 `--settings`"方式传入，不用 `type: ignore`（红线）；若只能 ignore，停下来问。
  - 选题阶段 `allow_web = False`，注释写明 M4 结合域名白名单再开；tech-debt 保留一行"联网域名策略"指向 M4。
- **测试**：单测断言生成的 sandbox 配置；冒烟新增用例：Bash `cat <workdir>/topic/x.md` 成功、`cat backend/.env` 失败。
- **完成标准**：冒烟日志存 `data/evidence/m1x/`；`make check` 绿。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`

### T9：OpenAI 路径 Shell 沙箱（TD-20）（待开始）

- **目标**：`LocalShellExecutor` 在 macOS 上经 `sandbox-exec` 运行，限制读、写和网络；其他平台不提供 Shell（失败关闭）。
- **涉及文件**：`backend/src/studio/agent/shell.py`（T6 产物）、新建 `backend/src/studio/agent/shell_sandbox.py`（生成 Seatbelt 配置）、`backend/src/studio/agent/openai_runtime.py`（`native_shell_supported` 增加平台条件）、`backend/tests/agent/test_shell_sandbox.py`、`docs/decisions/0009-Shell沙箱.md`、`docs/references/openai-agents-sdk.md`。
- **接口与要点**：
  - `seatbelt_profile(workdir: Path, deny_read: list[Path]) -> str`：`(allow default)` 基础上 `(deny file-write*)` 后放回 `workdir`、`/dev/null`、`/dev/tty`、专用临时目录（`workdir/.cache/tmp`，并把 `TMPDIR` 指向它）；`(deny file-read*)` 仓库根与 `data_dir`，放回 `workdir`；`(deny network*)`。路径需 `realpath`（macOS `/var` → `/private/var`）。
  - 执行方式：`create_subprocess_exec("/usr/bin/sandbox-exec", "-p", profile, "/bin/sh", "-c", command, ...)`，进程组语义不变。
  - `native_shell_supported` 在 `sys.platform != "darwin"` 或 `/usr/bin/sandbox-exec` 不存在时返回 False，走兜底只读工具。
  - `sandbox-exec` 已被 Apple 标为 deprecated 但仍可用，ADR 记录这一点和替代方案（容器）。
- **测试**：真实执行（本机 macOS）：写工作区成功、`cat` 仓库 `backend/.env` 返回非零、写 `~/` 下临时文件失败、`curl` 失败、`python3 -c 'print(1)'` 成功。非 darwin 时这些测试 `skipif(sys.platform != "darwin")`——理由：沙箱实现本身只在 macOS 存在，已在本计划写明（红线要求）。另有纯函数测试覆盖配置生成与平台判断（所有平台都跑）。
- **完成标准**：AC4 的证据；ADR 0009；`make check` 绿。
- **验证命令**：`make check`

### T10：收尾（待开始）

- **目标**：文档与质量评级同步，完成自验证与评审。
- **涉及文件**：`docs/quality/{tech-debt,QUALITY}.md`、`docs/ARCHITECTURE.md`、`docs/references/*`、本计划。
- **要点**：登记表移动已处理项、为不处理项补"去向"；L4 浏览器用 Fake 走一轮并截图（AC5）；本机登录冒烟全量跑一次；请独立评审者审查整个分支；负责人验收后按 SOP §8 合并。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`

## 进度

- 无

## 下一步

- 从 T1 开始（分支 `m1x-tech-debt`）。

## 决策记录

- 2026-09-28 — 范围取「小修 + 结构拆分」，TD-6/9/19/21/22/23/24 不在本计划 — 负责人选择；M2 会大量改 runner 与运行时，拆分放在之前成本最低。
- 2026-09-28 — TD-10 放在拆分（T6/T7）之前 — 拆分期间测试断言不动，才能证明是纯搬移。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 无
