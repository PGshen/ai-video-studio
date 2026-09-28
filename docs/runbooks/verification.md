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

- 命令：`make smoke`。它先导出 `backend/.env`（同 `scripts/dev.sh`），再在 `env -i` 白名单环境里运行 `cd backend && uv run pytest -m smoke -v -rs`；默认的 `make check` 用 `addopts = "-m 'not smoke'"` 排除这些用例。
- 用例（`backend/tests/smoke/test_smoke.py`），每种运行时/认证方式一个，都经 `TurnRunner` 在临时数据目录里跑真实的 turn：
  - `test_claude_api_key`：需要 `ANTHROPIC_API_KEY`（模型配置 `claude-sonnet`）；另跑一轮恢复会话，验证 API key 模式的会话存储（R4）。
  - `test_claude_login`：本机已登录的 Claude Code 订阅账号（`claude-login`），找不到 `claude` CLI 或设了 `STUDIO_SMOKE_SKIP_LOGIN=1` 时跳过；三轮：最小对话 → 恢复会话 + Bash 沙箱探测（R3、R4）→ 叙事阶段尝试写 `upstream/`（R5）。消耗订阅额度。
  - `test_openai_responses`：需要 `OPENAI_API_KEY`（`gpt`；设了 `STUDIO_OPENAI_BASE_URL` 时是对应网关的 key）。
  - `test_deepseek_litellm`：需要 `DEEPSEEK_API_KEY`（`deepseek`，LiteLLM 路径）；图片是否被看到只记录、不断言（R2）。
- 冒烟前在 `backend/.env` 设置网关（负责人要求，F2）：`STUDIO_ANTHROPIC_BASE_URL=https://ccproxy.yukework.com`（`test_claude_api_key` 经网关）、`STUDIO_OPENAI_BASE_URL=https://openrouter.ai/api/v1` 与 `STUDIO_OPENAI_MODEL=openai/gpt-6-luna`（必须选支持 `apply_patch` 工具的型号，gpt-5 不支持，见 ADR 0008）（`test_openai_responses` 经 OpenRouter，`OPENAI_API_KEY` 填 OpenRouter key）。`make smoke` 的白名单会带上所有 `STUDIO_*`，`build_harness` 用同一个 `Settings` 调种子，用例的模型配置从种子行复制，所以会用上这些值；不设则直连官方 API。经 OpenRouter 时 `gpt` 没有 Shell，用 `apply_patch` 建文件。
- 缺少某个 key 时，对应的用例会被跳过，并在输出中说明原因；结论记为"未验证"。
- 会产生真实的费用：每个用例只跑最小的对话。预算写在测试里（`COST_LIMITS` 合计 ≤ 1 美元、每轮最多 8 步），由模型配置的 `max_cost_per_turn`/`max_steps_per_turn` 强制；登录用例只限步数。
- 每个用例把观察结果写到 `data/evidence/m1/smoke/<时间>-<用例>.json`（形似 key 的字符串会被打码），建议同时 `make smoke 2>&1 | tee data/evidence/<计划 id>/smoke-runN.log`。
- `make smoke` 自己用 `env -i` 只带白名单变量运行 pytest：`HOME`、`PATH`、`USER`、`LANG`、`TMPDIR`、`SHELL`，加上导出 `backend/.env` 之后有值的 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`DEEPSEEK_API_KEY` 和所有 `STUDIO_*`。在 Claude Code 里代为运行时不需要再手动加 `env -i` 前缀；宿主注入的 `CLAUDE_CODE_*`/`ANTHROPIC_BASE_URL` 等变量不会进入用例（ClaudeRuntime 的 `build_env` 另外还会把它们置空，`make dev` 同样受保护）。
- 登录用例的会话 transcript 会留在 `~/.claude/projects/` 下（目录名由临时工作区路径推出），可以手动清理。
- **运行原则（负责人 2026-09-28）**：
  - 冒烟测试**不限制运行次数**，需要验证时就跑。
  - 用真实模型验证时，**优先使用本机登录的 Claude 订阅账号**（`claude-login`，不产生 API 费用）：`make smoke SMOKE_ARGS="-k claude_login"`。`SMOKE_ARGS` 原样追加到 pytest 命令后面。
  - 只有要验证的内容必须用到某个运行时或服务商时（API key 模式、OpenAI/OpenRouter、DeepSeek/LiteLLM），才跑对应用例或完整的 `make smoke`；这些用例会产生 API 费用，预算上限仍由测试里的 `COST_LIMITS` 强制。
