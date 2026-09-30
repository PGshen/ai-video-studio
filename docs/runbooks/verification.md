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
  - `test_volcengine_tts`（M3）：需要 `VOLCENGINE_TTS_API_KEY`（无 `STUDIO_` 前缀）。不经 `TurnRunner`，直接调 `VolcengineTTSEngine.synthesize` 合成一句很短的中文（真实付费，费用很小），断言音频非空、时长合理、逐字时间戳非空，再跑 `align_scene_beats` 检查覆盖率在 0–1 且 beat 起点单调。证据写到 `data/evidence/m3-narrative/smoke/`。命令：`make smoke SMOKE_ARGS="-k volcengine_tts"`。
  - `test_tavily_search`（M4）：需要 `TAVILY_API_KEY`（无 `STUDIO_` 前缀）。直接调 `TavilyProvider` 搜索一次、抓取一个结果（Tavily 免费额度，用量极小），断言有结果、URL 合法、至少一个页面抓取成功；观察写到 `data/evidence/m4-topic/smoke/`。命令：`make smoke SMOKE_ARGS="-k tavily"`。
  - `test_brainstorm_claude_login`（M4）：本机 Claude 登录，经 `TurnRunner` 跑一轮**无项目**的头脑风暴（真实的 brainstorm 阶段，`tools` 联网模式）：`list_ideas` → （有 `TAVILY_API_KEY` 时）`web_search` → `create_idea` ×2；断言 `ideas` 表里有卡片、`source_session_id` 正确、有反直觉点和评分，且 turn 没有快照。命令：`make smoke SMOKE_ARGS="-k brainstorm_claude_login"`。
  - `test_topic_claude_login` / `test_topic_claude_login_native_web`（M4）：本机 Claude 登录，真实的 topic 阶段。前者 `tools` 模式（需要 `TAVILY_API_KEY`）断言用了自建 `web_search`、没有原生联网；后者 `STUDIO_WEB_MODE=native`，断言用了原生 `WebSearch`/`WebFetch`、没有自建联网工具。两者都要求写出 `topic/brief.md` 且 `check_brief` 没有错误（允许一次「根据 check_brief 继续」的追加轮）。命令：`make smoke SMOKE_ARGS="-k topic_claude_login"`（一次约 3–4 分钟）。
  - `test_style_claude_login`（M5）：本机 Claude 登录，验证风格目录被按需读取。前置：先 `make export-legacy-styles`（旧项目 Postgres 容器在运行时只读导出到 `data/legacy-export/styles.json`；没有这个文件用例自动跳过）。用例在临时数据目录里导入它，用「概念传记·纸上溯源」建项目，叙事一轮（上游简报用 `tests/fixtures/narrative/brief.md` 定稿）断言动笔写 `narrative/narrative.json` **之前**读过 `style/STYLE.md`、`style/references/narrative-blueprint.md`、`style/exemplars/`，产物通过 `validate_narrative`；动画一轮（叙事换成 `tests/fixtures/animation/` 的 fixture 定稿）断言写 `animation/scenes/` 之前读过配色和动画风格，`validate_scenes` 通过；两轮都不写 `style/`。证据写到 `data/evidence/m5-polish/smoke/`。命令：`make smoke SMOKE_ARGS="-k style_claude_login"`（约 2 分钟）。
  - `test_model_switch_claude_login`（M5）：本机 Claude 登录，验证会话内换模型（ADR 0012）。同一个会话第一轮用 `claude-login`（`claude-sonnet-5`）说一条项目背景，用 `set_session_model_if_idle` 换成同一登录下的 Haiku 配置，第二轮问背景：断言 `sdk_ref` 不变、答得出、`usage.model` 是 Haiku、时间线上有一条 `model_switched` 的 `notice`。提示词不能用“暗号”之类的说法（模型会当成可疑指令拒绝，首次实测踩过）。命令：`make smoke SMOKE_ARGS="-k model_switch_claude_login"`（约 20 秒）。
  - `test_tts_preview_real`（M5）：需要 `VOLCENGINE_TTS_API_KEY`。经 `POST /api/tts/preview` 真实合成 5 段固定示例文本（`zizi` 1.0/0.5/2.0、`xiaohe` 1.2、`yunzhou` 1.0；真实付费，费用很小），断言状态、`audio/mpeg`、mp3 时长，边界语速 0.5/2.0 被接受且确实生效（0.5 比 1.0 长、2.0 比 1.0 短），同一组合第二次命中缓存（缓存文件数不变）。音频和观察写到 `data/evidence/m5-polish/smoke/`。命令：`make smoke SMOKE_ARGS="-k tts_preview_real"`（约 15 秒）。
- 冒烟前在 `backend/.env` 设置网关（负责人要求，F2）：`STUDIO_ANTHROPIC_BASE_URL=https://ccproxy.yukework.com`（`test_claude_api_key` 经网关）、`STUDIO_OPENAI_BASE_URL=https://openrouter.ai/api/v1` 与 `STUDIO_OPENAI_MODEL=openai/gpt-6-luna`（必须选支持 `apply_patch` 工具的型号，gpt-5 不支持，见 ADR 0008）（`test_openai_responses` 经 OpenRouter，`OPENAI_API_KEY` 填 OpenRouter key）。`make smoke` 的白名单会带上所有 `STUDIO_*`，`build_harness` 用同一个 `Settings` 调种子，用例的模型配置从种子行复制，所以会用上这些值；不设则直连官方 API。经 OpenRouter 时 `gpt` 没有 Shell，用 `apply_patch` 建文件。
- 缺少某个 key 时，对应的用例会被跳过，并在输出中说明原因；结论记为"未验证"。
- 会产生真实的费用：每个用例只跑最小的对话。预算写在测试里（`COST_LIMITS` 合计 ≤ 1 美元、每轮最多 8 步），由模型配置的 `max_cost_per_turn`/`max_steps_per_turn` 强制；登录用例只限步数。
- 每个用例把观察结果写到 `data/evidence/m1/smoke/<时间>-<用例>.json`（形似 key 的字符串会被打码），建议同时 `make smoke 2>&1 | tee data/evidence/<计划 id>/smoke-runN.log`。
- `make smoke` 自己用 `env -i` 只带白名单变量运行 pytest：`HOME`、`PATH`、`USER`、`LANG`、`TMPDIR`、`SHELL`，加上导出 `backend/.env` 之后有值的 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`DEEPSEEK_API_KEY`/`VOLCENGINE_TTS_API_KEY`/`TAVILY_API_KEY` 和所有 `STUDIO_*`。在 Claude Code 里代为运行时不需要再手动加 `env -i` 前缀；宿主注入的 `CLAUDE_CODE_*`/`ANTHROPIC_BASE_URL` 等变量不会进入用例（ClaudeRuntime 的 `build_env` 另外还会把它们置空，`make dev` 同样受保护）。
- 登录用例的会话 transcript 会留在 `~/.claude/projects/` 下（目录名由临时工作区路径推出），可以手动清理。
- **运行原则（负责人 2026-09-28）**：
  - 冒烟测试**不限制运行次数**，需要验证时就跑。
  - 用真实模型验证时，**优先使用本机登录的 Claude 订阅账号**（`claude-login`，不产生 API 费用）：`make smoke SMOKE_ARGS="-k claude_login"`。`SMOKE_ARGS` 原样追加到 pytest 命令后面。
  - 只有要验证的内容必须用到某个运行时或服务商时（API key 模式、OpenAI/OpenRouter、DeepSeek/LiteLLM），才跑对应用例或完整的 `make smoke`；这些用例会产生 API 费用，预算上限仍由测试里的 `COST_LIMITS` 强制。
