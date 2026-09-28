# 技术债登记表

发现暂时不处理的问题时登记在这里。每个里程碑收尾时，挑一两项处理，或者排进下一个计划。处理完的条目移到「已处理」。

| # | 登记日期 | 位置 | 问题 | 影响 | 建议的处理方式 | 来源 |
|---|---|---|---|---|---|---|
| TD-6 | 2026-09-28 | `agent/preamble.py: _upstream_changes`、`agent/stage_flow.py` | stale 判断按整项目快照 id，上游产物目录没变也会标 stale / 出现空的上游变更提示 | 多余的 stale 与空提示 | 按上游产物目录的清单比较（M3 做按镜头 id 的摘要时一起改） | M1 T6 审查 |
| TD-9 | 2026-09-28 | `agent/preamble.py: _user_edits` | 用户修改按路径合并窗口内所有 `user_edit` 快照，罕见情况下把其他阶段 agent 的改动算作用户修改 | 前言里的“用户修改”偶尔不准 | 只合并本会话窗口内、非 turn 产生的差异 | M1 T6 审查 |
| TD-14 | 2026-09-28 | `agent/shell.py: LocalShellExecutor` | `setsid` 主动脱离进程组的后台进程不会被 `killpg` 杀掉（drain 窗口取消已在 M1x T6 修复：显式取消并等待 reader） | 恶意命令可留下后台进程，且 sandbox-exec 下仍可能在沙箱写权限范围内活动 | 按会话 cgroup 或容器限制 | M1 T10 审查；M1x T6 修复 reader 部分 |
| TD-19 | 2026-09-28 | `agent/recovery.py: recover_on_startup`、`api/sessions.py: continue` | 重启后排队中的 turn 被标 `interrupted`；[继续] 只发“继续”，原消息没有重发 | 排队中的消息在重启后丢失语义 | 对从未开始的 turn 提供“重新发送原消息” | M1 最终审查（M5 处理） |
| TD-21 | 2026-09-28 | `agent/turn_events.py: handle`（tool_result） | 工具结果里的图片只持久化 `media_type`，不存内容 | 回放/刷新后看不到图片，前端只能显示占位文字 | M2 落地 `render_preview` 时把图片存进 blob 库 | M1 T6 / T13（M2 处理） |
| TD-22 | 2026-09-28 | `main.py` lifespan、uvicorn | uvicorn 收到 SIGTERM 后先等所有连接（含 SSE）关闭才执行 lifespan 关闭；`TurnRunner.shutdown` 在这之后才运行 | 实测：浏览器开着 SSE 时，优雅关闭期间运行中的 turn 先自然跑完，lifespan 的 interrupted 收尾很少真正触发；`kill -9`/崩溃仍由 `recover_on_startup` 兜底 | 关闭信号到达时主动结束 SSE 流，或设置 `--timeout-graceful-shutdown` | M1 最终审查 L3 实测（暂无实际症状，出现再处理） |
| TD-23 | 2026-09-28 | `api/files.py`、`api/snapshots.py`、`api/projects.py` | 为消除 TOCTOU，这些端点改成 `async def`，其中的同步 SQLite/文件 IO（回滚大工作区时可能上百毫秒）在事件循环上执行 | 回滚期间 SSE 等其他请求短暂卡顿 | 需要时改成 TurnRunner 的项目级 `asyncio.Lock` + 线程里做 IO | M1 最终审查 I4（暂无实际症状，出现再处理） |
| TD-24 | 2026-09-28 | `frontend/src/composables/useSessionStream.ts` | 时间线 `items` 无上限增长 | 超长会话内存与渲染变慢 | 分页或虚拟列表 | M1 T12 审查（暂无实际症状，出现再处理） |
| TD-25 | 2026-09-28 | `agent/claude_runtime.py`（成本账本）、`agent/turn_events.py: handle`（成本预算判断） | 会话首轮就被强制取消时，那一轮花费没有可归属的下一轮，直接丢失；`Usage.includes_carryover` 标注目前 runner/前端都不读，界面看不到“这笔花费含上一轮残余”；**且** runner 判断 `max_cost_per_turn` 时直接用含 carryover 的 `cost_usd`，两次连续强制取消叠加的极端场景下，下一轮本身没超预算也可能被误判 `budget_exceeded` | 极少数场景成本统计不完整、用户看不到含糊标注；更极端场景下会提前结束一轮本来在预算内的对话 | 首轮场景可考虑记一条“孤儿”账目供人工核对；runner 读取并透出 `includes_carryover` 给前端；判断预算时可考虑排除标记为 carryover 的部分，或至少提示用户这笔超支含上一轮残余 | M1x T3 审查；M1x 最终评审补充预算误判场景 |
| TD-26 | 2026-09-28 | `agent/claude_runtime.py: CostLedger` | resume 时若 `resume_ref` 回退到更早的会话 id（例如回滚后再次 resume 同一个已 `unsettled` 的旧会话），旧账目不会被清理，可能被重复标记 carryover；`total_cost_usd == 0` 的失败结果不会被标记 `unsettled`，其花费会被下一轮无声吸收 | 罕见场景下成本统计偏差 | resume 命中 fallback 账目时一并清理／标记；`_turn_cost` 对累计值为 0 的结果也标 unsettled | M1x T3 审查 |
| TD-27 | 2026-09-28 | `backend/src/studio/agent/shell_sandbox.py`、`backend/src/studio/agent/claude_scope.py: sandbox_settings`、`docs/decisions/0009-Shell沙箱.md` | 两条路径的 sandbox 都只拒读仓库根与 `data_dir`（OpenAI 路径见 `shell_sandbox.py`，Claude 路径见 `claude_scope.sandbox_settings`），`~/.ssh`、`~/.config`、keychain 列表等主目录路径仍可读；两边 Shell/Bash 都没有联网，但 stdout 会作为工具结果回给模型，等于多了一条不需要网络的外泄通道；setuid 二进制（如 `/bin/ps`）在 OpenAI 路径的沙箱里无法执行；登录模式下 `~/.claude/projects/<编码后的路径>/` 存的是本机**所有** studio 项目的会话 transcript（不只当前项目），同样在两条路径的拒读范围之外——比 `~/.ssh` 更窄但同样是真实缺口；本轮复核判断给它专门加 denyRead 有破坏 Claude CLI 自身会话记账的风险，需要单独在真机验证，不在本次修复预算内，先只记录 | 提示注入场景下主目录敏感文件、其他项目的会话记录可能经工具结果外泄；agent 用到 `ps` 等命令会意外失败 | 按需追加 `~/.ssh`、`~/.aws` 等 denyRead；`~/.claude/projects` 需要专门的真机验证再决定是否能拒读；ADR/参考文档补充 setuid 限制的说明 | M1x T9 审查；M1x 最终复核补充 Claude 路径与 `~/.claude/projects` |
| TD-28 | 2026-09-28 | `backend/src/studio/agent/claude_scope.py: sandbox_settings` | Bash 读不到仓库 `backend/.venv`、`frontend/node_modules`；M2 加 worker/渲染阶段如果需要 agent 在 Bash 里跑这些目录下的工具，需要把它们加入 `allowRead` | 目前无症状；M2 引入渲染/TTS 等重工具链时可能触发 | M2 需要时按目录加入 allowRead，而不是整体放开 denyRead | M1x T8 审查 |
| TD-29 | 2026-09-28 | `stages/topic/__init__.py: allow_web` | 选题阶段联网（WebSearch/WebFetch）在 M1x 暂时关闭，等域名白名单机制落地再开 | 选题阶段目前不能联网搜索 | M4 选题阶段落地时，结合域名白名单重新开启 `allow_web` | M1 最终审查 I5 → M1x T8（M4 处理） |
| TD-30 | 2026-09-28 | `scripts/dev.sh` | `python -m studio.config` 失败时，`read -r H P < <(...)` 在 `set -euo pipefail` 下直接终止脚本，加的 `-z` 检查是死代码，不会打印预期的清晰错误 | 启动失败时只看到 Python traceback，不够直观（行为与本计划改动前一致，不是新问题） | 改成 `if ! read -r H P < <(...); then echo ...; exit 1; fi` 这类显式检查 | M1x 最终评审复核发现，未修复 |
| TD-31 | 2026-09-28 | `backend/src/studio/workspace/scope.py: _prune_empty_ancestors` | 一轮内如果有两个兄弟子树都被判定越界还原（例如 `drafts/v1/a.md`、`drafts/v2/b.md`），它们各自的父目录会被清理，但共同的更上层祖先目录（如 `drafts/`）可能因为“先处理过的路径已经见过这个祖先”而被跳过，残留一个空目录 | 无功能影响（快照本来就不记录空目录），文件浏览器里偶尔会看到一个多余的空目录 | `_prune_empty_ancestors` 去掉 `seen_dirs` 提前退出，改成每次都重新检查是否为空（或按路径深度从深到浅统一处理） | M1x 最终评审复核（finding 4 修复引入的次要回归），未修复 |
| TD-32 | 2026-09-28 | `agent/stage.py: StageDefinition.tools()`、`agent/tools.py: ToolContext`、`stages/common/suggest_upstream_change.py` | `suggest_upstream_change` 需要一个 `Engine` 才能写 `suggestions` 表（`build_suggest_upstream_change_tool(engine) -> ToolSpec`），但 `StageDefinition.tools()` 是零参数方法，`TurnContext`/`ToolContext` 也没有 `Engine` 字段，所以这个工具目前没有接入 `AnimationStage.tools()`——真正被 agent 调用之前，还需要给"阶段工具如何拿到 db engine"这件事选一个方案（例如给 `ToolContext` 加 `Engine` 字段并在 `TurnRunner`/`main` 装配时传入，或者让 `StageRegistry.register` 时对每个阶段做一次"注入 engine"的组装） | `suggest_upstream_change` 目前只能被直接调用（测试），animation agent 实际对话中还调不到这个工具 | M2 剩余任务（T7–T14）里如果有任务自然会碰到这条线（例如某个阶段工具需要 engine），顺带定下方案并把这个工具接进去；否则留到 M3（narrative 也要用这个工具）一起解决 | M2 T6（决策记录 D22） |

## 已处理

| # | 处理日期 | 说明 |
|---|---|---|
| — | 2026-09-28 | M1 最终审查中直接修复的延后项：rollback 的 `..` 清单键测试（T3）、`upstream_drift` 对不可读文件的处理（T6）、未知图片块缺 `mimeType` 与客户端构造异常（T9）、继承宿主环境变量泄漏（T9，T15 已修）、T13/T14 浏览器中未实测的运行中状态（已补验，见 `data/evidence/m1/m6-l4-running-state.md`） |
| TD-1 | 2026-09-28 | M1x T8：Claude Bash sandbox 加 `filesystem.denyRead`（拒读仓库与 `data_dir`）+ `allowRead`（放回当前工作区）；选题阶段联网暂时关闭（域名白名单留给 M4，见 TD-29），见 `docs/references/claude-agent-sdk.md`、`data/evidence/m1x/` |
| TD-2 | 2026-09-28 | M1x T1：`scripts/dev.sh` 改为从 `python -m studio.config` 读取 host/port；最终复核发现 `frontend/vite.config.ts` 仍写死代理目标端口 8000，补上 `dev.sh` 导出 `STUDIO_BIND_PORT`、`vite.config.ts` 读它（缺省回退 8000），两者一起才算把 TD-2 覆盖完整 |
| TD-3 | 2026-09-28 | M1x T1：`config.py` 暴露公开 `repo_root()`，测试不再引用私有常量 |
| TD-4 | 2026-09-28 | M1x T1：`create_snapshot` 复用扫描时读到的内容，已存在的 blob 不再重复读文件 |
| TD-5 | 2026-09-28 | M1x T1：`HIDDEN_TOP_DIRS` 下沉到 `workspace/layout.py`，`list_tree`/`read_text` 统一过滤；`guard` 还原后清理空目录 |
| TD-7 | 2026-09-28 | M1x T2：`recover_on_startup` 对 `running` 的 turn 按阶段 `write_scope` 做一次越界还原（`_guard_recovered_turn`），再做 partial 快照 |
| TD-8 | 2026-09-28 | M1x T2：`_after_tool_result` 识别 `path`/`file_path`/`notebook_path`/`move_to` 并去重；`_truncate_value` 递归截断嵌套参数 |
| TD-10 | 2026-09-28 | M1x T4：完整一轮的测试改为断言相对顺序与类型计数（`backend/tests/event_asserts.py`），为 T7 的纯搬移铺路 |
| TD-11 | 2026-09-28 | M1x T3：成本账本统一用 SDK 会话 id 记账，取消而未拿到 result 时标记 `unsettled`，下一轮以 `includes_carryover` 标注差值；残余边界见 TD-25、TD-26 |
| TD-12 | 2026-09-28 | M1x T3：`run_turn` 在 connect 前后检查取消令牌，`max_cost_per_turn == 0` 直接拒绝不连 SDK |
| TD-13 | 2026-09-28 | 随 TD-8 一并修复（`_after_tool_result` 识别 `file_path`/`notebook_path`） |
| TD-15 | 2026-09-28 | M1x T7：`agent/runner.py` 拆分为 `runner.py`/`turn_state.py`/`turn_events.py`/`turn_finish.py`/`recovery.py`，622→340 行 |
| TD-16 | 2026-09-28 | M1x T6：`agent/openai_runtime.py` 拆分出 `agent/shell.py`、`agent/openai_tools.py`，764→362 行；T9 接入 Shell 沙箱又加了代码，复核时实测为 764→374 行 |
| TD-17 | 2026-09-28 | M1x T5：新增 `TurnContext.tool_context()`，三个运行时统一通过它构造 `ToolContext` |
| TD-18 | 2026-09-28 | M1x T5：步数预算只由 runner 计数（`_handle(ToolCall)` → `_exceed_budget`），运行时不再各自计步 |
| TD-20 | 2026-09-28 | M1x T9：OpenAI 路径 `LocalShellExecutor` 经 macOS `sandbox-exec` 执行（拒读仓库与 `data_dir`、只写工作区、禁网）；非 macOS 或无 `sandbox-exec` 时不提供 Shell，见 ADR `docs/decisions/0009-Shell沙箱.md`、`data/evidence/m1x/` |
