# 自验证方法

SOP 的第 4 阶段（自验证）要求：**每条验收标准都有实际运行的证据**。证据的层级如下，按需选用，越往下越接近真实使用。

| 层级 | 方法 | 什么时候用 |
|---|---|---|
| L1 | `make check` | 每个任务都要跑 |
| L2 | 针对性的 pytest（`-k`），或者用 FakeRuntime 做端到端测试 | 验证后端流程 |
| L3 | `curl` 调用运行中的 api，SSE 用 `curl -N` 观察 | 验证接口和流式行为 |
| L4 | 在浏览器中操作前端并截图（Claude 桌面版的内置浏览器：用 `.claude/launch.json` 中的配置启动 `preview_start`） | 验证界面和交互 |
| L5 | `make smoke`：真实模型、真实 key | 验证运行时适配器和风险项 R1–R5 |

## 记录证据

- 在计划的「验证记录」一节，逐条写明：验收标准编号、执行的命令或操作、输出摘要、结论。
- 截图和日志放在 `data/evidence/<计划 id>/`（不进 git），计划里写明路径。
- 如果某条验收标准无法验证（例如缺少 key），就明确写出"未验证"和原因，不能写成"通过"。

## 冒烟测试（`make smoke`）

- 命令：`make smoke`。它先导出 `backend/.env`（同 `scripts/dev.sh`），再运行 `cd backend && uv run pytest -m smoke -v -rs`；默认的 `make check` 用 `addopts = "-m 'not smoke'"` 排除这些用例。
- 用例（`backend/tests/smoke/test_smoke.py`），每种运行时/认证方式一个，都经 `TurnRunner` 在临时数据目录里跑真实的 turn：
  - `test_claude_api_key`：需要 `ANTHROPIC_API_KEY`（模型配置 `claude-sonnet`）；另跑一轮恢复会话，验证 API key 模式的会话存储（R4）。
  - `test_claude_login`：本机已登录的 Claude Code 订阅账号（`claude-login`），找不到 `claude` CLI 或设了 `STUDIO_SMOKE_SKIP_LOGIN=1` 时跳过；三轮：最小对话 → 恢复会话 + Bash 沙箱探测（R3、R4）→ 叙事阶段尝试写 `upstream/`（R5）。消耗订阅额度。
  - `test_openai_responses`：需要 `OPENAI_API_KEY`（`gpt`）。
  - `test_deepseek_litellm`：需要 `DEEPSEEK_API_KEY`（`deepseek`，LiteLLM 路径）；图片是否被看到只记录、不断言（R2）。
- 缺少某个 key 时，对应的用例会被跳过，并在输出中说明原因；结论记为"未验证"。
- 会产生真实的费用：每个用例只跑最小的对话。预算写在测试里（`COST_LIMITS` 合计 ≤ 1 美元、每轮最多 8 步），由模型配置的 `max_cost_per_turn`/`max_steps_per_turn` 强制；登录用例只限步数。
- 每个用例把观察结果写到 `data/evidence/m1/smoke/<时间>-<用例>.json`（形似 key 的字符串会被打码），建议同时 `make smoke 2>&1 | tee data/evidence/<计划 id>/smoke-runN.log`。
- 在 Claude Code 里代为运行时，用 `env -i HOME=... PATH=... make smoke` 之类去掉宿主注入的 `CLAUDE_CODE_*`/`CLAUDECODE`/`ANTHROPIC_BASE_URL` 等变量，让登录用例的环境与普通终端一致。
- 登录用例的会话 transcript 会留在 `~/.claude/projects/` 下（目录名由临时工作区路径推出），可以手动清理。
- 运行冒烟测试需要负责人事先同意（SOP §6 第 7 条），计划中已写明的除外。
