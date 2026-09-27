# 技术债登记表

发现暂时不处理的问题时登记在这里。每个里程碑收尾时，挑一两项处理，或者排进下一个计划。处理完的条目移到「已处理」。

| # | 登记日期 | 位置 | 问题 | 影响 | 建议的处理方式 | 来源 |
|---|---|---|---|---|---|---|
| TD-1 | 2026-09-28 | `backend/src/studio/agent/claude_runtime.py`（`WEB_TOOLS`、`SANDBOX`） | Claude agent 开联网时 WebFetch/WebSearch 放行所有域名；SDK sandbox 只管 Bash 且默认不限制读，Bash 能读工作区外文件（如 `backend/.env`），再经 WebFetch 外发 | 提示注入场景下本机文件可能外泄（密钥类环境变量已置空、Read/Glob/Grep 已限制在工作区内，见 references/claude-agent-sdk.md） | sandbox `filesystem.denyRead` 拒读仓库与 `data/`；WebFetch 域名白名单或按阶段默认关闭联网 | M1 最终审查 I5 |
| TD-2 | 2026-09-28 | `scripts/dev.sh`、`backend/src/studio/config.py` | `Settings.host`/`port` 没被 `dev.sh` 使用，uvicorn 的 host/port 在脚本里写死 | 改 `STUDIO_PORT` 不生效，容易误以为改了端口 | dev.sh 从 Settings 读取（或删掉这两个字段） | M1 T1 审查 |
| TD-3 | 2026-09-28 | `backend/tests/test_config.py` | 测试直接引用私有常量 `_REPO_ROOT`/`_BACKEND_SRC_DIR` | 重构 config 时测试跟着破 | 暴露只读的公开函数或只断言行为 | M1 T1 审查 |
| TD-4 | 2026-09-28 | `workspace/snapshot.py: create_snapshot` | 扫描时读一遍文件算 sha，写 blob 时再读一遍 | 大工作区快照多一倍 IO | scan 返回内容或按 sha 判断 blob 已存在就跳过读取 | M1 T3 审查 |
| TD-5 | 2026-09-28 | `workspace/files.py: list_tree/read_text`、`workspace/scope.py: guard` | `list_tree`/`read_text` 不排除 `EXCLUDED_TOP_DIRS`（api 层自己过滤）；guard 还原后不清理空目录 | 别的调用方可能读到 `.cache/`、`output/`；越界新建的空目录残留 | 在 workspace 层统一过滤；guard 末尾复用 `_prune_empty_dirs` | M1 T4 审查 |
| TD-6 | 2026-09-28 | `agent/preamble.py: _upstream_changes`、`agent/stage_flow.py` | stale 判断按整项目快照 id，上游产物目录没变也会标 stale / 出现空的上游变更提示 | 多余的 stale 与空提示 | 按上游产物目录的清单比较（M3 做按镜头 id 的摘要时一起改） | M1 T6 审查 |
| TD-7 | 2026-09-28 | `agent/runner.py: recover_on_startup` | 重启恢复只做 `partial` 快照，不做越界检查（工具写入记录随进程丢失） | 进程崩溃那一轮的越界改动会留在工作区 | 恢复时至少按可写范围做一次无工具记录的 guard | M1 T6 审查 |
| TD-8 | 2026-09-28 | `agent/runner.py: _after_tool_result/_truncate_args` | 文件工具的 `path` 与 recorded 路径可能重复推送；`_truncate_args` 只截断顶层字符串 | SSE 里路径重复；嵌套大参数不截断 | 去重；递归截断 | M1 T6 审查 |
| TD-9 | 2026-09-28 | `agent/preamble.py: _user_edits` | 用户修改按路径合并窗口内所有 `user_edit` 快照，罕见情况下把其他阶段 agent 的改动算作用户修改 | 前言里的“用户修改”偶尔不准 | 只合并本会话窗口内、非 turn 产生的差异 | M1 T6 审查 |
| TD-10 | 2026-09-28 | `backend/tests/api/test_stream.py`、`tests/agent/test_runner.py` | 完整一轮的测试断言精确事件顺序 | runner 调整事件顺序时测试要同步改 | 只断言相对顺序或按类型分组 | M1 T8 审查 |
| TD-11 | 2026-09-28 | `agent/claude_runtime.py: CostLedger/_turn_cost` | transcript 无累计值时少算；读用 `resume_ref`、写用 `session_id`；强制取消后本轮花费会计入下一轮 | 登录模式/中断场景下成本统计偏差 | 统一用 SDK 会话 id；取消时尽量读取最后一条 result | M1 T9 审查 |
| TD-12 | 2026-09-28 | `agent/claude_runtime.py: run_turn` | connect 期间已取消不会立即结束（等 runner 10s 宽限期）；`max_cost_per_turn=0` 时 CLI 不强制 | 取消响应慢；0 预算不生效 | connect 前后检查取消令牌；0 预算直接拒绝 | M1 T9 审查 |
| TD-13 | 2026-09-28 | `agent/runner.py: _after_tool_result` | runner 从 `args["path"]` 取改动路径，Claude 原生写工具参数是 `file_path` | Claude 写文件时 `workspace_changed` 路径为空（前端整体刷新，功能不受影响） | 同时识别 `file_path`/`notebook_path` | M1 T9 审查 |
| TD-14 | 2026-09-28 | `agent/openai_runtime.py: LocalShellExecutor` | drain 窗口内取消没有显式取消 reader 任务；`setsid` 逃逸出进程组的后台进程不会被杀 | 少量资源泄漏；恶意命令可留下后台进程 | 显式取消 reader；按会话 cgroup/沙箱限制 | M1 T10 审查 |
| TD-15 | 2026-09-28 | `agent/runner.py`（566 行） | 超过约 400 行的建议上限 | 可读性、审查成本 | 把排队调度、事件处理、收尾拆成独立模块 | M1 T6 / 最终审查 |
| TD-16 | 2026-09-28 | `agent/openai_runtime.py`（688 行） | 文件过大，`LocalShellExecutor` 与运行时混在一起 | 同上 | 把 Shell executor 拆到独立模块 | M1 T10 / 最终审查 |
| TD-17 | 2026-09-28 | `agent/claude_runtime.py`、`agent/openai_runtime.py`、`agent/fake.py` | `ToolContext` 构造重复三处 | 新增字段容易漏改 | 在 `TurnContext` 上提供 `tool_context()` | M1 最终审查 |
| TD-18 | 2026-09-28 | `agent/runner.py`、各运行时 | 步数预算在 runner 和运行时两处计算 | 两处计数口径可能不一致 | 以 runner 为准，运行时只做兜底 | M1 最终审查 |
| TD-19 | 2026-09-28 | `agent/runner.py: recover_on_startup`、`api/sessions.py: continue` | 重启后排队中的 turn 被标 `interrupted`；[继续] 只发“继续”，原消息没有重发 | 排队中的消息在重启后丢失语义 | 对从未开始的 turn 提供“重新发送原消息” | M1 最终审查 |
| TD-20 | 2026-09-28 | `agent/openai_runtime.py: LocalShellExecutor` | OpenAI/LiteLLM 路径的 Shell 没有沙箱：能读本机任意文件、写工作区内任意路径 | 提示注入场景下风险高于 Claude 路径 | 接入 sandbox-exec / 容器，或默认关闭 Shell | M1 T10 / 最终审查 |
| TD-21 | 2026-09-28 | `agent/runner.py: _handle`（tool_result） | 工具结果里的图片只持久化 `media_type`，不存内容 | 回放/刷新后看不到图片，前端只能显示占位文字 | M2 落地 `render_preview` 时把图片存进 blob 库 | M1 T6 / T13 |
| TD-22 | 2026-09-28 | `main.py` lifespan、uvicorn | uvicorn 收到 SIGTERM 后先等所有连接（含 SSE）关闭才执行 lifespan 关闭；`TurnRunner.shutdown` 在这之后才运行 | 实测：浏览器开着 SSE 时，优雅关闭期间运行中的 turn 先自然跑完，lifespan 的 interrupted 收尾很少真正触发；`kill -9`/崩溃仍由 `recover_on_startup` 兜底 | 关闭信号到达时主动结束 SSE 流，或设置 `--timeout-graceful-shutdown` | M1 最终审查 L3 实测 |
| TD-23 | 2026-09-28 | `api/files.py`、`api/snapshots.py`、`api/projects.py` | 为消除 TOCTOU，这些端点改成 `async def`，其中的同步 SQLite/文件 IO（回滚大工作区时可能上百毫秒）在事件循环上执行 | 回滚期间 SSE 等其他请求短暂卡顿 | 需要时改成 TurnRunner 的项目级 `asyncio.Lock` + 线程里做 IO | M1 最终审查 I4 |
| TD-24 | 2026-09-28 | `frontend/src/composables/useSessionStream.ts` | 时间线 `items` 无上限增长 | 超长会话内存与渲染变慢 | 分页或虚拟列表 | M1 T12 审查 |

## 已处理

| # | 处理日期 | 说明 |
|---|---|---|
| — | 2026-09-28 | M1 最终审查中直接修复的延后项：rollback 的 `..` 清单键测试（T3）、`upstream_drift` 对不可读文件的处理（T6）、未知图片块缺 `mimeType` 与客户端构造异常（T9）、继承宿主环境变量泄漏（T9，T15 已修）、T13/T14 浏览器中未实测的运行中状态（已补验，见 `data/evidence/m1/m6-l4-running-state.md`） |
