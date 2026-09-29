# M4：选题（选题打磨阶段、选题池与头脑风暴、搜索提供方与 Tavily）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | M4 |
| 设计依据 | [架构设计 §4.2、§4.3、§5.0、§5.1、§6.2、§6.3、§10](../../design/2026-09-26-architecture.md) |
| 分支 | `m4-topic` |
| 批准记录 | 2026-09-29：负责人批准计划，D1 修改为「联网模式开关」（见决策记录，`STUDIO_WEB_MODE=tools\|native`）；执行方式为当前会话内联执行；T13 使用真实 Tavily key 已获同意，key 已填入 `backend/.env` |

## 目标

用户打开「选题池」页，和头脑风暴 agent 对话，agent 联网搜索并把想法写成卡片（反直觉点、四项评分、标签）；用户在卡片上点「创建项目」，进入该项目的选题打磨阶段：agent 联网调研，把 `topic/brief.md`（固定七个章节、每条关键事实带出处和把握程度）和 `topic/notes/` 打磨好，`check_brief` 通过后用户定稿，叙事阶段解锁（M3 已实现）。至此整条流水线「选题池 → 选题 → 叙事 → 动画」第一次能不靠手工 fixture 从头走通。

## 范围

**包含：**

- `search`：搜索提供方接口（`search`、`extract`）+ Tavily 实现；key 走裸环境变量 `TAVILY_API_KEY`（和 `VOLCENGINE_TTS_API_KEY` 同一原则，不进 `Settings`）。
- 联网工具 `web_search` / `fetch_url`（`stages/common`，供 brainstorm 和 topic 两个阶段、所有运行时统一使用），带「URL 来源」限制（D3）；**联网模式开关** `STUDIO_WEB_MODE`：`tools`（默认，自建工具）或 `native`（Claude WebSearch/WebFetch、OpenAI 托管 `WebSearchTool`），两种模式互斥（D1）。TD-29 在默认模式下关闭，`native` 模式的已知风险写进 ADR 0010。
- 选题池：`ideas` 仓储与 REST 接口（列表/新建/编辑/归档）、按想法卡片创建项目（写入 `idea_id`、卡片置为 `picked`、把卡片内容种进项目的 `topic/notes/`）。
- 头脑风暴阶段 `stages/brainstorm`：阶段定义、提示词、`list_ideas` / `create_idea` / `update_idea`，以及 TurnRunner 对「没有项目、没有工作区」的会话的支持（D2）。
- 选题打磨阶段 `stages/topic`：`brief.md` 结构与 `check_brief`（工具 + `GET /projects/{id}/topic/check` 接口）、完整提示词、注册联网工具。
- 前端：`features/ideas/`（卡片网格、筛选、编辑、归档、创建项目、头脑风暴抽屉）、`features/canvas/topic/`（简报渲染/编辑、检查状态、笔记列表），接入 `IdeasPage.vue` 和 `ProjectWorkbenchPage.vue`。
- 文档：ADR 0010、`references/tavily.md`、runbook 冒烟用例、QUALITY/ARCHITECTURE/tech-debt 更新。

**不包含：**

- 风格库与风格选择（M5）。创建项目仍复制占位 `STYLE.md`，「创建项目」对话框不带风格选择器。
- 回退建议的完整体验（M5）。topic 没有上游阶段，本计划不给它接 `suggest_upstream_change`。
- 头脑风暴会话的模型选择默认值/阶段默认模型设置（M5 设置页）；本计划沿用现有「模型配置下拉」。
- 选题卡片的硬删除、卡片之间的合并/去重 UI；只有归档。
- 域名白名单式的联网限制（被 D3 的「URL 来源」规则取代；`native` 模式不受该规则保护，理由见 D1/D3）。
- 在前端设置页切换联网模式（M5 设置页）；本计划只提供后端环境变量开关。
- 后端在 `finalize` 时强制 `check_brief` 通过（D4，沿用 M3 对叙事阶段的处理）。

## 验收标准

- [ ] AC1：`TavilyProvider.search`/`extract` 在 mock HTTP 下返回规范化结果；401/429/5xx/超时/畸形 JSON 各自给出明确的、不含 key 的错误；缺 `TAVILY_API_KEY` 时 `build_search_provider()` 抛 `RuntimeError`（验证：`pytest backend/tests/search/`）
- [ ] AC2：`tools` 模式下 `web_search`/`fetch_url` 可用于 brainstorm 和 topic，不可用于 narrative/animation；`fetch_url` 拒绝不是来自本会话搜索结果或用户消息的 URL，拒绝非 http(s)、带账号密码的、指向 localhost/内网 IP 的 URL；超长网页被截断并注明；搜索/抓取失败作为 `is_error` 工具结果返回而不是让一轮失败（验证：`pytest backend/tests/stages/test_web_tools.py`）
- [ ] AC3：联网模式开关生效：`tools`（默认）下三个运行时都不向模型暴露原生联网工具，只有自建工具；`native` 下 Claude 暴露 WebSearch/WebFetch、OpenAI（官方 API 路径）暴露 `WebSearchTool`，且自建的 `web_search`/`fetch_url` 不出现，narrative/animation 在任何模式下都没有联网能力；`STUDIO_WEB_MODE` 写了非法值时启动报错（验证：`pytest backend/tests/agent/test_web_mode.py backend/tests/test_config.py`）
- [ ] AC4：`ideas` 仓储与 `/api/ideas*` 覆盖：新建、列表（按状态筛选）、编辑、归档/恢复；标题归一化后重复的卡片被拒；`scores` 只接受四个已知维度且值在 1–5；不存在的 id 返回 404（验证：`pytest backend/tests/db/test_ideas_repo.py backend/tests/api/test_ideas.py`）
- [ ] AC5：`POST /api/brainstorm/sessions` 创建无项目的头脑风暴会话；用 `FakeRuntime` 跑一轮：turn 完成、事件落库、SSE 可回放、没有创建任何快照、scratch 目录被重置、重启恢复把遗留 turn 标为 `interrupted`；同一时刻多个头脑风暴会话和项目 turn 互不阻塞（验证：`pytest backend/tests/agent/test_runner_brainstorm.py backend/tests/api/test_brainstorm_sessions.py`）
- [ ] AC6：头脑风暴 agent 的三个工具：`list_ideas` 返回卡片摘要，`create_idea` 写入 `source_session_id`、拒绝重复标题并说明与哪张卡片重复，`update_idea` 只能改自己允许改的字段；项目阶段调用这些工具报错（验证：`pytest backend/tests/stages/test_brainstorm_tools.py`）
- [ ] AC7：`check_brief` 对合法简报通过；对缺章节、章节为空、关键事实为空、事实缺出处或把握程度给出点名的错误；低把握事实、章节顺序错乱只给警告；文件缺失/非 UTF-8 不抛异常（验证：`pytest backend/tests/stages/test_topic_brief.py`）
- [ ] AC8：`POST /api/projects` 带 `idea_id` 时：项目 `idea_id` 已设置、卡片变为 `picked` 且记录 `project_id`、`topic/notes/idea-card.md` 在初始快照里；卡片不存在或已被选走返回 4xx 且不留半成品项目（验证：`pytest backend/tests/api/test_projects.py`）
- [ ] AC9：端到端（`FakeRuntime`）：头脑风暴一轮创建卡片 → 从卡片创建项目 → topic 一轮写 `brief.md`、调用 `check_brief` → 定稿 → 叙事阶段变 `active` 且 `upstream/topic/brief.md` 可读（验证：`pytest backend/tests/api/test_topic_flow.py`）
- [ ] AC10：前端选题池页面：卡片网格、状态筛选、编辑、归档、创建项目并跳转；头脑风暴抽屉里 agent 新建的卡片无需刷新即出现；选题画布显示渲染后的简报、`check_brief` 错误/警告、笔记列表，可切换编辑（验证：`pnpm exec vitest run` 的纯逻辑用例 + L4 走查，截图见「验证记录」）
- [ ] AC11：`make check` 全绿
- [ ] AC12：真实冒烟：`make smoke SMOKE_ARGS="-k tavily"`（真实 Tavily key）通过；本机 Claude 登录在 `tools` 模式下跑一轮真实的头脑风暴（联网搜索 → 创建卡片）和一轮选题打磨（搜索 → 抓取 → 写简报 → `check_brief`），并在 `native` 模式下再跑一轮选题打磨确认开关有效（验证：`make smoke SMOKE_ARGS="-k topic_claude_login"`，证据在 `data/evidence/m4-topic/`）

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->
<!-- 依赖顺序：T1 → T5；T2 → T4/T7/T9；T3 → T4；T5、T6 → T8；T8 → T12。前端 T9–T11 各自只依赖对应的后端任务，可以在后端任务完成后开始。 -->

### T1：`search` 模块——提供方接口与 Tavily 实现（完成）

- **目标**：`backend/src/studio/search/` 提供与具体供应商无关的 `SearchProvider` 协议和 Tavily 实现，作为纯能力层（只依赖 `config`，不访问数据库，不知道项目和阶段）。
- **涉及文件**：
  - 新建 `backend/src/studio/search/{__init__,base,tavily,factory}.py`。
  - 新建 `backend/tests/search/test_tavily.py`（`respx` 已是测试依赖，M3 T1 引入）。
  - `backend/pyproject.toml`：补 import-linter 契约「`search` 只依赖 `config`」（ARCHITECTURE §2 规则 4，M2 T1 对 `engines` 的同款 `forbidden` 契约照抄）。
  - `backend/.env.example`：补 `TAVILY_API_KEY` 说明（放在 `VOLCENGINE_TTS_API_KEY` 旁边）。
  - 新建 `docs/references/tavily.md`，`docs/references/README.md` 补索引。
- **接口与要点**：
  - `base.py`：`SearchHit(title, url, snippet, published: str | None, score: float | None)`、`SearchResponse(query, hits)`、`ExtractedPage(url, text, truncated: bool)`、`SearchError(Exception)`（`retryable: bool`、面向模型的中文 `message`，不含 key）；`SearchProvider` 协议：`async search(query, *, max_results=5, recency_days=None) -> SearchResponse`、`async extract(url, *, max_chars) -> ExtractedPage`。
  - `tavily.py`：`httpx.AsyncClient` 直连，`Authorization: Bearer`；具体端点、字段、免费额度、错误码**先查 Tavily 官方文档并写进 `references/tavily.md`（注明日期和来源）**，不凭训练记忆；超时、有限次重试（只重试 429/5xx/超时）沿用 `engines/tts/volcengine.py` 的写法。
  - `factory.py`：`build_search_provider() -> TavilyProvider`，缺 `TAVILY_API_KEY` 抛 `RuntimeError`（消息指向 `backend/.env`）。
  - 不新增依赖（`httpx` 已有）。抓取网页正文由 Tavily 的 extract 完成，本项目不自己发起对任意站点的请求（D1 的理由之一：没有本机 SSRF 面）。
- **测试**：搜索成功路径（结果规范化、`max_results` 生效）；`extract` 成功与超长截断；401（key 无效，错误消息不含 key）、429/5xx 重试到耗尽、超时、响应不是 JSON/缺字段各自转成 `SearchError`；空查询直接拒绝不发请求；缺 key 抛 `RuntimeError`。
- **完成标准**：`pytest backend/tests/search/` 通过；无真实网络请求；import-linter 新契约生效。
- **验证命令**：`make check`

### T2：`ideas` 仓储与 REST 接口（完成）

- **目标**：选题池卡片的持久化和 HTTP 接口，供头脑风暴工具（T4）、创建项目（T7）和前端（T9）共用。
- **涉及文件**：新建 `backend/src/studio/db/repo/ideas.py`、`backend/src/studio/api/ideas.py`；改 `api/schemas.py`（`IdeaOut`/`IdeaCreate`/`IdeaUpdate`）、`main.py`（挂路由）；测试 `backend/tests/db/test_ideas_repo.py`、`backend/tests/api/test_ideas.py`。**不需要新迁移**：`ideas` 表在 0001 已建好。
- **接口与要点**：
  - `IdeaValue`（与其他仓储一致的只读值对象）；`create_idea` / `get_idea` / `list_ideas(status=None)` / `update_idea` / `find_duplicate(title)`。
  - `scores` 固定四个键：`counterintuitive`、`provable`、`visual`、`novelty`，值为 1–5 的整数，缺省的键不算错（agent 可能只评了部分）；`tags` 是字符串列表，去重、去空白、最多 8 个。校验放在仓储层的一个纯函数里，工具和 API 共用。
  - 重复判定：标题去首尾空白、统一全半角和大小写后相等。
  - 状态：`idea`/`picked`/`archived`。API 只允许 `idea ⇄ archived`；`picked` 只能由创建项目（T7）设置，`picked` 的卡片不能被归档、标题不能改。
  - 接口：`GET /api/ideas?status=`（缺省返回 `idea` + `picked`，`status=archived`/`all` 可选；按 `created_at` 倒序）、`POST /api/ideas`（手动新建）、`PATCH /api/ideas/{id}`。不提供 DELETE。
- **测试**：仓储：增改查、重复标题（含全半角/大小写变体）、`scores` 非法键/越界值/非整数、标签清洗；API：状态筛选、`picked` 卡片不可归档不可改名、404、422。
- **完成标准**：上述测试通过；`api` 与 `db.repo` 的分层契约不受影响。
- **验证命令**：`make check`

### T3：无项目会话——TurnRunner 的「无工作区」模式与头脑风暴会话接口（完成）

- **目标**：让 `project_id is None` 的会话能跑完整的一轮（D2）：没有快照、没有 `upstream/`、没有越界检查，只有事件、用量、状态；同时提供创建和列出头脑风暴会话的接口。这是本计划里改动面最大的一步，其余后端任务不依赖它以外的运行时改动，所以先做。
- **涉及文件**：
  - `backend/src/studio/agent/runner.py`（`start_turn` 不再对 `project_id is None` 直接抛错、`_execute` 分支、调度用 `busy_key`）、`agent/turn_state.py`（`_Job.project_id: str | None`）、`agent/turn_finish.py`、`agent/recovery.py`、`agent/runtime.py`（`TurnContext.project_id: str | None`、新增 `session_id: str`）、`agent/tools.py`（`ToolContext.project_id: str | None`、新增 `session_id: str | None = None`、`require_project() -> str`）。
  - 已有的项目阶段工具（`validate_scenes`、`render_preview`、`validate_narrative`、`synthesize_tts`、`suggest_upstream_change`）改用 `ctx.require_project()`；先 `grep -rn "ctx.project_id" backend/src` 列全。
  - `workspace/layout.py` + `workspace/files.py`：`scratch_dir(data_dir, session_id)`（`data/scratch/<session_id>/`）、`reset_scratch(...)`（删除并重建为空目录）。
  - 新建 `backend/src/studio/api/brainstorm.py`：`POST /api/brainstorm/sessions`（校验与 `create_session_endpoint` 相同：模型配置存在、运行时已启用）、`GET /api/brainstorm/sessions`；`main.py` 挂路由。会话的 `messages`/`cancel`/`continue`/`stream` 复用现有的 `/api/sessions/{id}/*`（它们本来就只按会话 id 查）。
  - 测试：新建 `backend/tests/agent/test_runner_brainstorm.py`、`backend/tests/api/test_brainstorm_sessions.py`；改 `test_tools.py`、`test_recovery`（若有）中构造 `ToolContext` 的地方（新字段有默认值，应无需改动）。
- **接口与要点**：
  - 无项目模式的一轮：`workdir = scratch_dir(...)`，每轮开始前 `reset_scratch`（Claude 的原生 Write/Bash 可能在里面留东西，下一轮不该看到）；`write_scope` 为空（`WriteScope(writable=[], tool_managed=[])`）；不建快照、不物化 `upstream/`、不算前言（`compose_user_text` 收空前言）；`turn_finish` 跳过 guard/快照/`after_turn_done`，其余（`error` 事件、用量、写 turn 状态、发布 `turn_status`）不变；`start_snapshot_id`/`end_snapshot_id` 保持 `NULL`。
  - 调度：`is_project_busy` 只对项目 turn 有意义；无项目 turn 用「会话 id」作为 `busy_key`，不阻塞项目 turn，也不被项目 turn 阻塞，仍受 `max_concurrent_turns` 全局上限约束。
  - `create_session(project_id=None, stage="brainstorm")` 时「同一阶段其他会话取消活动」的 SQL 要对 `project_id IS NULL` 正确生效——加测试，别假设 `== None` 已经生效。
  - `recovery.py` 已经有 `session.project_id` 的判断，确认无项目 turn 只标 `interrupted`，不进 `_guard_recovered_turn`。
  - 前端已有的 `SessionOut.project_id: string | null` 类型不用改。
- **测试**：`FakeRuntime` 跑无项目一轮：`turns` 状态 `done`、无 `snapshot` 事件、`start/end_snapshot_id` 为空、scratch 目录在轮开始时是空的（上一轮留下的文件被清掉）；取消、失败、`budget_exceeded` 各走一遍且不抛；一个无项目 turn 与一个项目 turn 同时运行不互相排队；重启恢复；同会话第二条消息在第一轮运行中仍返回 409；`GET /api/brainstorm/sessions` 只返回头脑风暴会话；模型配置不存在/运行时未启用给 400；项目阶段的会话仍在 `project_id=None` 时被拒绝（防止误建）。
- **完成标准**：M1–M3 的全部既有 agent/API 测试不改断言仍然通过（仅允许因签名新增字段而改构造处）。
- **验证命令**：`make check`

### T4：`stages/brainstorm`——阶段定义、三个工具、提示词（待开始）

- **目标**：头脑风暴 agent 能列出已有卡片、创建卡片、修改卡片（设计 §5.0）；阶段注册进 `main`。
- **涉及文件**：新建 `backend/src/studio/stages/brainstorm/{__init__,prompt.md,tools.py}`；改 `backend/src/studio/main.py`（注册）、`backend/pyproject.toml`（把 `studio.stages.brainstorm` 加进「各阶段互不 import」的 `independence` 契约）；测试 `backend/tests/stages/test_brainstorm_tools.py`、`backend/tests/stages/test_brainstorm_prompt.py`，`test_placeholders.py` 里补 `TestBrainstormStage`。
- **接口与要点**：
  - `BrainstormStage`：`name="brainstorm"`，`upstream_stages()`/`artifact_dirs()` 为空，`write_scope()` 为空，`status_summary(workdir)` 返回固定说明（它没有工作区）。
  - 工具（`stages={"brainstorm"}`，都读 `ctx.engine`，`engine is None` 时按 `suggest_upstream_change` 的写法返回内部错误）：
    - `list_ideas(status?: "idea"|"picked"|"archived", query?: str)` → 每张卡片一行摘要（id、标题、状态、标签、总分），上限 50 条并注明是否截断，供 agent 查重。
    - `create_idea(title, pitch, counterintuitive, tags?, scores?)` → 校验（T2 的纯函数）、查重（重复时报出已有卡片的 id 和标题）、写 `source_session_id=ctx.session_id`。一次只创建一张；批量产出靠 agent 多次调用。
    - `update_idea(id, pitch?, counterintuitive?, tags?, scores?, title?)` → 只能改 `status=idea` 的卡片；`picked`/`archived` 的拒绝并说明。不提供改状态的参数（归档由用户在界面做）。
  - 提示词（`prompt.md`）：目标是**发散**而不是打磨；每张卡片必须有一个明确的「反直觉点」（一句话说清「大家以为 X，实际是 Y」）；四项评分的含义和 1–5 的标定（避免全给 4、5）；创建前先 `list_ideas` 查重；联网搜索用来验证「反直觉」是否成立、找新鲜度，不是抄选题；一次对话建议产出 3–6 张；不要替用户选题。关键词断言的轻量提示词测试，同 `test_narrative_prompt.py`。
- **测试**：工具三件套各自的成功和错误路径（重复标题、非法分数、改 `picked` 卡片、`engine is None`、在 topic 阶段调用被拒——通过 `ToolSpec.stages` 断言）；`tools()` 名称集合；提示词关键词。
- **完成标准**：`pytest backend/tests/stages/` 通过。
- **验证命令**：`make check`

### T5：联网工具 `web_search`/`fetch_url` 与联网模式开关（待开始）

- **目标**：brainstorm 和 topic 有两种可切换的联网方式：`tools`（默认）用自建的 `web_search`/`fetch_url`，「URL 来源」规则挡住提示注入外泄；`native` 用各运行时的原生联网能力。由 `STUDIO_WEB_MODE` 控制，两种模式互斥（D1、D3）。
- **涉及文件**：
  - 新建 `backend/src/studio/stages/common/web_tools.py`（`WEB_SEARCH_TOOL`、`FETCH_URL_TOOL`）；`stages/topic/__init__.py`、`stages/brainstorm/__init__.py` 的 `tools()` 接入，两个阶段的 `allow_web = True`（含义改为「本阶段允许联网」，具体用哪种方式由模式决定；`narrative`/`animation` 仍是 `False`）。
  - `backend/src/studio/config.py`：`Settings.web_mode: Literal["tools", "native"] = "tools"`（`STUDIO_WEB_MODE`）；`.env.example` 补说明。
  - `backend/src/studio/agent/tools.py`：常量 `WEB_TOOL_NAMES = frozenset({"web_search", "fetch_url"})`（`agent` 不 import `stages`，所以名字定义在这一层）。
  - `backend/src/studio/agent/runner.py`：`_execute` 里 `allow_web = stage.allow_web and settings.web_mode == "native"`；`tools = stage.tools()`，`native` 模式下滤掉名字在 `WEB_TOOL_NAMES` 里的工具，`tools` 模式保持不变。`claude_runtime.py`/`openai_runtime.py` 里现有的 `allow_web` 分支不改，继续负责暴露原生工具。
  - 新建 `docs/decisions/0010-联网模式开关.md`（D1、D3；标明对 ADR 0004 和设计 §4.2「联网」一行的偏离：默认不再用原生联网，原生联网保留为可选模式；ADR 0004 状态改为「部分被 0010 取代」）；`docs/references/claude-agent-sdk.md` 中「M4 结合域名白名单再开」的两处文字改为指向 ADR 0010；`docs/quality/tech-debt.md` 的 TD-29 在 T14 处理。
  - 测试：新建 `backend/tests/stages/test_web_tools.py`、`backend/tests/agent/test_web_mode.py`，补 `backend/tests/test_config.py`。
- **接口与要点**：
  - `web_search(query, max_results?=5, recency_days?)`：调用 `build_search_provider()`（模块级 `_PROVIDER_FACTORY`，测试用 `monkeypatch` 替换，同 M3 的 `_ENGINE_FACTORY`）；返回编号列表（标题、URL、发布时间、摘要），并把结果 URL 记入**本会话的搜索结果集合**（进程内 `dict[session_id, set[str]]`，URL 先做规范化：小写主机名、去 fragment、去末尾 `/`）。
  - `fetch_url(url, max_chars?=12000)`：允许的 URL 只有两类——① 本会话 `web_search` 返回过的；② 本会话任一条用户消息里出现过的（从 `turns.user_message` 用正则取出，走 `ctx.engine`，进程重启后仍成立）。其余一律拒绝，并告诉模型「先用 web_search 找到它，或请用户把链接贴出来」。另外拒绝：非 http(s)、含 `user:pass@`、主机名是 IP 字面量或 `localhost`/`*.local`/`*.internal`。返回正文，超出 `max_chars` 截断并注明「已截断，共 N 字」。
  - 工具的 `stages={"brainstorm","topic"}`；`SearchError` 转成 `is_error=True` 的结果（`retryable` 时提示可稍后再试）；缺 key 时错误信息说明去 `backend/.env` 配置 `TAVILY_API_KEY`。
  - `native` 模式没有 URL 来源保护，也不需要 Tavily key；OpenAI 路径经 OpenRouter 等非官方 `base_url` 时托管 `WebSearchTool` 是否可用未验证，结论在 T13 冒烟后写进 ADR 0010。
  - 两个阶段的提示词写成与模式无关：说「联网搜索/抓取网页」，不写死工具名（T4/T6 遵守）。
  - 搜索结果集合在会话结束后不清理（进程内，量很小）；无上限增长的问题登记 tech-debt，不做 LRU。
- **测试**：`tools` 模式：搜索成功且 URL 被记录、随后 `fetch_url` 该 URL 成功；未搜索过的 URL 被拒；用户消息里贴的 URL 可抓取（真实 `turns` 行）；重启（清空进程内集合）后用户贴的 URL 仍可抓取而搜索结果 URL 需要重新搜索；各类被拒 URL；截断提示；`SearchError` 三种（无 key、429、超时）转成错误结果；`web_mode` 非法值 `Settings` 校验失败。模式开关：用 `FakeRuntime` 记录收到的 `TurnContext`，断言 `tools` 模式下 `allow_web=False` 且工具列表含两个自建工具，`native` 模式下 `allow_web=True` 且两个自建工具被滤掉；narrative/animation 两种模式下都是 `allow_web=False` 且没有自建联网工具；既有 Claude/OpenAI 运行时测试里 `allow_web` 分支的断言继续通过。
- **完成标准**：AC2、AC3。
- **验证命令**：`make check`

### T6：`stages/topic`——`brief.md` 结构、`check_brief`、完整提示词（待开始）

- **目标**：选题简报有机器可检查的结构；agent 用 `check_brief` 自查，画布用同一份检查结果显示状态。
- **涉及文件**：新建 `backend/src/studio/stages/topic/brief.py`（解析与检查，纯函数）、`stages/topic/check_brief.py`（工具）、`backend/src/studio/api/topic.py`（`GET /api/projects/{id}/topic/check`，读工作区 `topic/brief.md` 调用 `brief.check`）；改 `stages/topic/__init__.py`（`tools()`）、`stages/topic/prompt.md`（改写成完整版）、`main.py`（挂路由）；更新 `backend/tests/fixtures/narrative/brief.md` 使其通过 `check_brief`（先 `grep -rn "brief" backend/tests` 确认没有测试断言它的具体文字）；测试 `backend/tests/stages/test_topic_brief.py`、`test_topic_check_tool.py`、`test_topic_prompt.py`、`backend/tests/api/test_topic_check.py`。
- **接口与要点**：
  - 常量 `SECTIONS`：核心问题、钩子与反直觉点、目标观众与前置知识、关键事实、叙事角度与结构草图、可视化机会、风险点（二级标题，顺序即设计 §5.1 的顺序）。
  - 「关键事实」章节的每个列表项遵循 `- 事实陈述（出处：<URL 或文献>；把握程度：高|中|低）`；解析容忍全半角冒号/逗号/分号和括号。
  - `check(text: str | None) -> BriefCheck(errors: list[str], warnings: list[str])`：
    - 错误：文件缺失或为空；缺章节（点名）；章节存在但正文为空；「关键事实」没有任何列表项；某条事实缺「出处」或「把握程度」不在 高/中/低 内（点名第几条并引用前 20 字）。
    - 警告：有把握程度为「低」的事实（报条数）；章节顺序与 `SECTIONS` 不一致；出现不认识的二级标题；「风险点」不足 20 字。
    - 输入不是合法 UTF-8 时由调用方（工具/接口）先转成错误，`check` 本身只接收 `str | None`。
  - 工具 `check_brief`（无入参，`stages={"topic"}`）：错误 → `is_error=True` 列出全部；只有警告 → 正常返回并附警告；全部通过 → 「简报结构检查通过」。
  - 提示词：七章节的写作要求；事实条目格式；出处必须来自本会话真实的 `web_search`/`fetch_url` 结果，**不能凭记忆编造 URL**；调研笔记写进 `topic/notes/<主题>.md` 并在简报里引用；想法卡片在 `topic/notes/idea-card.md`（T7 种入），先读它；写完先 `check_brief`；对「关键事实」中把握程度低的条目要么补证据要么删掉；不要自己定稿。
  - `write_scope` 保持 `topic/**`；`status_summary` 补充「brief.md 是否存在、check 的错误/警告条数」。
- **测试**：`check` 的每条错误和警告各一个用例（用子串断言）、全半角标点变体、事实列表混入非列表段落、`None`/空串；工具三种返回；API：项目不存在 404、`brief.md` 缺失返回 `errors` 而非 404、`brief.md` 不是 UTF-8 返回错误；提示词关键词断言。
- **完成标准**：AC7；`tools()` 名称集合为 `{"web_search","fetch_url","check_brief"}`（与 T5 合并后）。
- **验证命令**：`make check`

### T7：从想法卡片创建项目（待开始）

- **目标**：设计 §5.0 的「选中卡片后即可创建项目」：项目关联卡片，卡片内容成为 topic 阶段 agent 的输入。
- **涉及文件**：`backend/src/studio/api/projects.py`（`create_project_endpoint`、`_init_workspace`）、`api/schemas.py`（`ProjectCreate.idea_id: str | None = None`）、`db/repo/ideas.py`（`mark_picked(engine, idea_id, project_id)`，只在 `status == "idea"` 时成功）；测试 `backend/tests/api/test_projects.py`。
- **接口与要点**：
  - 带 `idea_id`：先校验卡片存在且 `status == "idea"`（否则 404/409，此时没有任何副作用）；工作区初始文件多一个 `topic/notes/idea-card.md`（标题、一句话卖点、反直觉点、标签、四项评分，Markdown），随 `init` 快照落盘；项目 `idea_id` 写入；成功后 `mark_picked`。
  - 失败清理沿用 `_cleanup_failed_project`；`mark_picked` 是创建流程的最后一步（项目行、阶段行都已写成功之后）。它失败时卡片本来就没有改动，所以只需清理项目，不需要还原卡片；`mark_picked` 用条件更新（`WHERE status='idea'`）保证并发下两个项目不会抢同一张卡片，输的一方按失败清理并返回 409。
  - 项目标题：请求体的 `title` 仍是必填，前端默认预填卡片标题。
  - 不带 `idea_id` 的既有创建路径行为不变。
- **测试**：正常创建（卡片 `picked`、`project_id` 回填、`idea-card.md` 内容含标题和反直觉点、在 init 快照里）；卡片不存在 → 404 且没有新项目；卡片已 `picked` → 409；卡片 `archived` → 409；`mark_picked` 抛错时项目被清理。
- **完成标准**：AC8。
- **验证命令**：`make check`

### T8：后端端到端——选题池到叙事解锁（待开始）

- **目标**：把 T2–T7 拼起来的契约测试，避免各自通过但拼不上（M3 T8 的同一思路）。
- **涉及文件**：新建 `backend/tests/api/test_topic_flow.py`。
- **接口与要点**：
  - `FakeRuntime` 剧本 1（头脑风暴会话）：`call_tool list_ideas` → `call_tool create_idea` ×2（其中第三次故意重复标题，断言工具错误被 agent 看到但本轮不失败）→ `TurnEnd`。
  - 用其中一张卡片 `POST /api/projects`（带 `idea_id`）。
  - 剧本 2（topic 会话）：读到 `idea-card.md` 的前提用 `write` 步骤写 `topic/brief.md`（合法版本）→ `call_tool check_brief` → `TurnEnd`；再在另一轮里故意写缺章节的版本，断言 `check_brief` 返回错误且 `GET /topic/check` 与之一致。
  - 定稿 topic → 叙事阶段 `active`；`materialize_upstream` 后 `upstream/topic/brief.md` 内容与定稿时一致；M3 的 `test_narrative_flow.py` 不需要改动仍然通过。
  - 联网工具用 `monkeypatch` 替换 `_PROVIDER_FACTORY`；剧本里加一步 `call_tool web_search` + `fetch_url`，断言 `fetch_url` 对未搜索过的 URL 报错。
- **测试**：即本文件。
- **完成标准**：AC9。
- **验证命令**：`make check`

### T9：前端 `features/ideas/`——选题池页面（待开始）

- **目标**：`/ideas` 从占位页变成真正的选题池：卡片网格、筛选、编辑、归档、创建项目。抽屉里的头脑风暴对话在 T10 接入，本任务先留出布局位置。
- **涉及文件**：
  - 新建 `frontend/src/features/ideas/IdeaCard.vue`、`IdeaGrid.vue`、`IdeaEditDialog.vue`、`CreateProjectDialog.vue`。
  - 新建 `frontend/src/features/ideas/ideaView.ts`（纯逻辑：四项评分转总分、按状态/标签筛选、标签输入清洗、评分维度的中文标签；`ideaView.spec.ts`）。
  - 改 `frontend/src/api/endpoints.ts`（`listIdeas`、`createIdea`、`updateIdea`、创建项目请求带 `idea_id`）、`types/api.ts`、`composables/queries.ts`（`useIdeasQuery`、`useUpdateIdeaMutation`、`useCreateIdeaMutation`；`queryKeys.ideas(status)`），并补 `endpoints.spec.ts`/`queries.spec.ts` 对应用例。
  - 改 `frontend/src/pages/IdeasPage.vue`（组合层）。
- **接口与要点**：
  - 卡片显示标题、一句话卖点、「反直觉点」（突出）、标签、四个评分（小条形）；状态 `picked` 的卡片显示「已创建项目」并链接到该项目；`archived` 默认隐藏，可通过筛选查看并「恢复」。
  - 「创建项目」对话框：标题预填卡片标题，可改；成功后 `router.push('/projects/:id/topic')`（同 `ProjectList.vue`），并使 `ideas` 和 `projects` 查询失效。
  - 空状态文案引导用户开始头脑风暴（T10 接入后有按钮）。
  - 分层规则：`features/ideas` 不 import 其他 `features/*`；需要共用的（例如下一任务的会话面板）通过 `components/` 或 `composables/`。
- **测试**：`ideaView.spec.ts` 覆盖总分计算（缺维度按已有维度算并注明）、筛选、标签清洗；`endpoints.spec.ts` 覆盖新端点的请求形状；组件不做挂载测试（沿用既有策略），靠 L4。
- **完成标准**：`pnpm exec vitest run` 通过；`make check`（含 lint 分层规则）通过。
- **验证命令**：`make check`

### T10：头脑风暴抽屉——会话面板泛化与卡片实时刷新（待开始）

- **目标**：在选题池页右侧抽屉里和头脑风暴 agent 对话；agent 创建/修改卡片时卡片网格不用刷新就更新。
- **涉及文件**：
  - 改 `frontend/src/features/workbench/SessionPicker.vue`、`SessionPanel.vue`：`projectId`/`stage` 属性泛化为一个 `scope`（`{ kind: 'project', projectId, stage } | { kind: 'brainstorm' }`），纯逻辑（例如 scope → 查询键、`SessionPanel` 中依赖 `projectId` 的图片 blob URL）抽到 `features/workbench/sessionScope.ts` + `sessionScope.spec.ts`。
  - 改 `frontend/src/api/endpoints.ts`（`listBrainstormSessions`、`createBrainstormSession`）、`composables/queries.ts`（`useSessionsQuery`/`useCreateSessionMutation` 接受 scope）、`composables/useSessionStream.ts`（无项目会话在 `tool_result` 和终态 `turn_status` 时使 `ideas` 查询失效；已有的 `if (projectId)` 分支对无项目会话本来就跳过，确认没有空指针）。
  - 新建 `frontend/src/features/ideas/BrainstormDrawer.vue`（复用 `SessionPicker` + `SessionPanel`，用现有 shadcn `Sheet`，若组件库里没有先用 CLI 添加，不手写）；`IdeasPage.vue` 挂接。
  - **分层**：`features/ideas` 不能 import `features/workbench`。`SessionPicker`/`SessionPanel` 现在在 `features/workbench`，要被两个 feature 共用，所以本任务把它们连同 `SessionTimelineItem.vue` 和纯逻辑文件一起移到 `frontend/src/components/session/`（`components/` 不能 import `features/`——先确认它们没有依赖 `features/` 内的东西）；`ProjectWorkbenchPage.vue` 的 import 跟着改；ARCHITECTURE §3 的表同步更新。
- **接口与要点**：无新后端接口；「失效 `ideas` 查询」用事件类型 + 工具名后缀匹配（`create_idea`/`update_idea`，兼容 Claude 侧 `mcp__studio__` 前缀），不新增 SSE 事件类型。
- **测试**：`sessionScope.spec.ts`；`useSessionStream.spec.ts` 补「无项目会话不访问项目查询键、`create_idea` 的 `tool_result` 使 `ideas` 失效」；搬移后 M1 的既有 vitest 全部不改断言仍然通过。
- **完成标准**：`pnpm exec vitest run` 通过；`make check`。
- **验证命令**：`make check`

### T11：前端 `features/canvas/topic/`——选题画布，接入工作台（待开始）

- **目标**：`stage === 'topic'` 时显示专属画布（简报渲染视图/编辑模式、`check_brief` 状态、笔记列表），并完成对话面板的联网工具展示。
- **涉及文件**：
  - 新建 `frontend/src/features/canvas/topic/TopicCanvas.vue`（外壳）、`BriefView.vue`（渲染，用项目已依赖的 `vue-stream-markdown`；用法先看 `components/ai-elements/message/MessageResponse.vue`，不新增依赖）、`BriefCheckBar.vue`、`NotesList.vue`。
  - 新建 `frontend/src/features/canvas/topic/briefStatus.ts`（纯逻辑：把 `GET /topic/check` 的结果变成「可以定稿 / 有 N 个错误 / 有 N 条警告」的提示条状态）+ `briefStatus.spec.ts`。
  - 改 `api/endpoints.ts`（`getTopicCheck`）、`composables/queries.ts`（`useTopicCheckQuery`；在 `invalidateWorkspace` 里一并使它失效——`workspace_changed` 和一轮结束时都会触发）；`pages/ProjectWorkbenchPage.vue` 加 `v-else-if="stage === 'topic'"` 分支。
  - 工具调用的展示：`web_search`/`fetch_url` 的结果在时间线里已按通用工具卡片显示，检查长 URL/长正文不撑破布局；必要时只调样式。
- **接口与要点**：
  - 简报视图和 JSON 标签页一样，可编辑（复用 `components/CodeEditor.vue`，Markdown 语言已在依赖里）；缓冲区/冲突处理沿用 `NarrativeCanvas.vue` 的简化写法，不 import 其他 feature。
  - 提示条与 M3 一致：**不**禁用「定稿」按钮（`StageNav` 在 `features/workbench`，不能被画布依赖，且 D4），只在画布顶部显示 `check_brief` 状态。
  - `brief.md` 不存在时显示空状态并说明「和 agent 对话开始选题打磨」。
  - 笔记列表读 `topic/notes/**`，点开在画布内渲染（只读，编辑可切换）。
- **测试**：`briefStatus.spec.ts`；组件走 T12 的 L4。
- **完成标准**：`pnpm exec vitest run`、`make check` 通过。
- **验证命令**：`make check`

### T12：L4 端到端走查（待开始）

- **目标**：按浏览器实际操作走一遍完整链路，并把发现的问题修掉。参照 M3 T11：Claude 桌面版内置浏览器由控制者截图。
- **涉及文件**：视发现的问题而定；截图和记录写进「验证记录」（浏览器工具不能落盘时如实说明，M3 已有先例）。
- **接口与要点**：用 `make dev` + `STUDIO_ENABLE_FAKE_RUNTIME=true` 走一遍（Fake 剧本可复现），再用本机 Claude 登录（免费，SOP §6 第 7 条例外）走一遍真实对话。检查点：
  1. `/ideas` 空状态 → 打开抽屉 → 新建头脑风暴会话 → 发消息 → 卡片实时出现；
  2. 编辑、归档、恢复卡片；
  3. 「创建项目」→ 跳转 topic 画布，`idea-card.md` 在笔记列表里；
  4. topic 对话：agent 搜索、抓取、写简报；画布在 agent 运行时只读、结束后可编辑；
  5. 故意删掉一个章节 → 提示条列出错误；补上并给出出处 → 提示条变绿；
  6. 定稿 → 导航显示叙事变为可用，进入叙事阶段能读到简报（M3 已有画布）；
  7. 项目列表里该项目可点回；选题池里对应卡片显示「已创建项目」。
- **测试**：无新增自动化测试；发现的每个 bug 先补一个能复现的测试再修（SOP §4）。
- **完成标准**：上述七点通过，问题和修复记入「意外与发现」。
- **验证命令**：`make dev` 手动走查

### T13：真实冒烟——Tavily 与 Claude 登录下的选题流程（待开始）

- **目标**：用真实服务确认联网工具和两个阶段的提示词在真模型下可用。
- **涉及文件**：`backend/tests/smoke/test_smoke.py`（新增 `test_tavily_search`、`test_brainstorm_claude_login`、`test_topic_claude_login`，都带 `@pytest.mark.smoke`）、`backend/tests/smoke/support.py`（`M4_EVIDENCE_DIR`）、`Makefile`（`smoke` 目标的 `env -i` 白名单加 `TAVILY_API_KEY`）、`docs/runbooks/verification.md`（用例表加三行）、`docs/references/tavily.md`（补真实调用观察到的行为：响应延迟、结果字段、extract 对常见站点的表现，注明日期）。
- **接口与要点**：
  - `test_tavily_search`：用一个简短的固定查询，断言有结果、URL 合法、`extract` 其中一条得到非空正文；缺 `TAVILY_API_KEY` 时 `pytest.skip`。用量极小，Tavily 免费额度足够。
  - `test_brainstorm_claude_login`：真实模型经 `TurnRunner`，指令固定为「围绕一个话题创建 2 张卡片」，断言 `ideas` 表里出现 ≥1 张卡片、含 `source_session_id`、本轮没有 `failed`；需要 `TAVILY_API_KEY` 才跑联网部分，没有时把用例降级为不要求搜索。
  - `test_topic_claude_login`（`tools` 模式）与 `test_topic_claude_login_native_web`（`native` 模式，通过 `STUDIO_WEB_MODE=native` 构造运行时，不要求 Tavily key，断言原生 WebSearch 被调用过）：先用 fixture 建一个带卡片的项目，跑一轮选题打磨，断言 `topic/brief.md` 存在且 `check` 没有错误（真实模型偶尔会写不齐，允许用例内**一次**「根据 `check_brief` 结果继续」的追加轮，不允许更多）。
  - 证据落 `data/evidence/m4-topic/smoke/`，沿用 `record_evidence`（含 key 打码）。
- **测试**：即用例本身。
- **完成标准**：本机设置 `TAVILY_API_KEY` 后三条用例通过；未设置时 Tavily 相关部分显示 `SKIPPED`。
- **验证命令**：`make smoke SMOKE_ARGS="-k tavily"`、`make smoke SMOKE_ARGS="-k topic_claude_login"`、`make smoke SMOKE_ARGS="-k brainstorm_claude_login"`

### T14：文档与收尾（待开始）

- **目标**：按 SOP §7 收尾清单更新文档，让代码与文档一致。
- **涉及文件**：`docs/ARCHITECTURE.md`（`search`、`stages.brainstorm`、`stages.common` 联网工具、无项目会话、前端 `features/ideas`、`features/canvas/topic`、`components/session`，`search` 已有契约的说明）、`docs/quality/QUALITY.md`（`stages.brainstorm`、`stages.topic`、`search`、`frontend`、`api`、`agent` 评级）、`docs/quality/tech-debt.md`（关闭 TD-29；登记本计划中确认要推迟的项，例如进程内搜索结果集合无上限、`SessionOut.is_active` 对头脑风暴会话的语义）、`docs/references/legacy-assets.md`（如果这个里程碑有迁移项则更新，否则不动）、`docs/glossary.md`（想法卡片、选题简报、头脑风暴、无项目会话）、`docs/runbooks/dev-setup.md`（`TAVILY_API_KEY`）、`AGENTS.md`（若命令有变化）。
- **接口与要点**：无。
- **测试**：`scripts/check_docs.py` 通过。
- **完成标准**：`make check` 通过（文档检查项）；SOP §7 清单逐项勾选后再走验收。
- **验证命令**：`make check`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-09-29 — T1 `search` 模块（Tavily 提供方、工厂、import-linter 契约、references/tavily.md）— 31 个新测试通过，`make check` 全绿（commit 见 git log）
- 2026-09-29 — T2 `ideas` 仓储与 `/api/ideas` — 47 个新测试通过，`make check` 全绿（commit 见 git log）
- 2026-09-29 — T3 无项目会话（TurnRunner 无工作区模式、`ToolContext.require_project`、scratch 目录、`/api/brainstorm/sessions`、brainstorm 阶段骨架）— 新增 30 个测试，既有测试不改断言全部通过，`make check` 全绿（commit 见 git log）

## 下一步

- 做 T4：`stages/brainstorm` 已有骨架（`__init__.py`、占位 `prompt.md`，`tools()` 为空，`allow_web=False`）。先写 `backend/tests/stages/test_brainstorm_tools.py`、`test_brainstorm_prompt.py`（失败），再新建 `stages/brainstorm/tools.py`（`list_ideas`/`create_idea`/`update_idea`，读 `ctx.engine` 和 `ctx.session_id`，仓储函数见 `db/repo/ideas.py`）并把 `prompt.md` 改写成完整版；`tools()` 接入三个工具。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-09-29：起草计划时提出的草案决定（**需要负责人批准**；执行中如与实际不符以执行时的决策记录为准）：
  - **D1 联网模式开关（负责人 2026-09-29 批准时修改）。** 设计 §4.2 的联网行是「Claude 用原生 WebSearch/WebFetch、OpenAI 用托管 `WebSearchTool`、其他模型兜底 Tavily」。改为 `STUDIO_WEB_MODE` 开关：`tools`（**默认**）三条路径都用自建的 `web_search`/`fetch_url`（Tavily 后端）；`native` 沿用设计原意。两种模式互斥，避免模型同时看到两套联网工具。默认选 `tools` 的理由：① 原生联网工具能访问任意域名，正是 TD-29 当初关闭它的原因，原生工具没有域名限制的接入点，只有 Claude 侧的 `PreToolUse` hook 能拦，OpenAI 托管的搜索在服务端执行，拦不住；② OpenAI 路径经 OpenRouter 时托管 `WebSearchTool` 本来就不一定可用；③ 一套工具、一套测试，三种运行时行为一致；④ 抓取由 Tavily 远端完成，本机没有 SSRF 面，也不新增依赖。`native` 模式的代价：没有 D3 的 URL 来源保护（提示注入外泄风险回到 TD-29 当初的状态），由使用者自行承担，在 ADR 0010 写明。开关只在后端环境变量；前端设置页里切换留给 M5。偏离 ADR 0004 和设计 §4.2 的默认行为，所以写 ADR 0010（设计文档不改，红线）。
  - **D2 头脑风暴会话没有工作区。** 设计 §4.3 说 brainstorm「可写：无」，§3.1 说头脑风暴会话 `project_id` 为空。做法：`project_id is None` 的会话走 TurnRunner 的「无工作区」模式，cwd 是每轮重置的空 scratch 目录 `data/scratch/<session_id>/`（原生文件工具需要一个 cwd），不做快照/越界检查。不选「给头脑风暴造一个伪项目」：会污染项目列表和快照表，还得给它特殊状态。
  - **D3 `fetch_url` 用「URL 来源」规则，不做域名白名单。** 调研需要访问任意公开站点，静态白名单不可行；真正要防的是提示注入让模型把工作区文本拼进一个攻击者的 URL 再抓取。规则：只能抓本会话搜索结果里出现的 URL 或用户自己贴的 URL，模型不能凭空构造 URL。残余风险：搜索查询本身会发给 Tavily（可信第三方，接受）；攻击者若能让自己的页面进入搜索结果，可以拿到一次带 URL 的抓取，但 URL 内容是搜索返回的、不含工作区文本。
  - **D4 `check_brief` 不在后端 `finalize` 强制。** 设计 §5.1 的定稿条件是「`check_brief` 没有错误，由用户确认」；沿用 M3 对叙事阶段的处理（画布提示条 + 用户确认），理由相同：`StageNav` 和画布分属不同 feature，禁用按钮要把状态提到页面层，而定稿本来就由用户确认。如负责人希望后端强制，是一个独立的小任务（`StageDefinition` 加可选的 `finalize_blockers(workdir)`），可以追加到本计划。
  - **D5 风格仍是占位。** 设计 §5.0 说创建项目时「复制所选风格」；风格库是 M5，本计划继续复制占位 `STYLE.md`，不做风格选择器。
  - **D6 一张卡片只创建一个项目。** 创建项目后卡片置为 `picked` 并记录 `project_id`，不能再次创建、不能归档、不能改名；想再做一次同题材，让 agent 新建一张卡片。设计的 `ideas.status` 只有 `idea/picked/archived` 三态，没有「多个项目」的语义。
- 2026-09-29（T1 执行中）：`recency_days` 映射到 Tavily 的 `time_range`（≤1 天 day、≤7 week、≤31 month、其余 year），因为 Tavily 只接受这四档；`extract` 结果多出 `total_chars` 字段（截断前长度），供 `fetch_url` 提示「共 N 字」；432/433（额度）单独归为不可重试并提示额度问题。
- 2026-09-29（T2 执行中）：`mark_picked` 用 `UPDATE ... WHERE status='idea' RETURNING id` 做条件更新（pyright 不认 `Result.rowcount`）；`update_idea` 的「没传 vs 传 None」用 `UNSET` 哨兵区分；API 的 `PATCH` 用 `model_fields_set` 判断，`tags`/`scores` 传 `null` 视为清空。评分接受整数值浮点数（`4.0` → 4），因为模型的 JSON 偶尔会写成浮点。
- 2026-09-29（T3 执行中）：① brainstorm 阶段骨架（`stages/brainstorm/`、注册进 `main`、进 `independence` 契约）提前到 T3，因为 API 和运行时测试需要一个真实注册的阶段；T4 只补工具和提示词。② 「哪些阶段无项目」用常量 `agent.stage.WORKSPACELESS_STAGES = {"brainstorm"}`，不给 `StageDefinition` 协议加字段——协议改动会波及所有阶段和测试桩。`start_turn` 双向校验：无项目会话必须是这些阶段，这些阶段的会话不能属于项目；项目阶段的会话创建接口对 `brainstorm` 返回 404。③ `TurnRunner` 新增 `is_session_busy(session_id)`（测试用，也可供 API 用）；调度键 `_Job.busy_key`（项目 id 或 `session:<id>`）。④ `turn_finish.finish` 拆成 `_guard_workspace`/`_snapshot_workspace` 两个私有函数，行为不变，无项目会话跳过两者和 `after_turn_done`。⑤ `default_fake_script` 在阶段没有可写路径时只回显，不再抛 `ValueError`（否则 `make dev` 的 fake 运行时跑不了头脑风暴）。⑥ brainstorm 的 `allow_web` 暂为 `False`，T5 加联网模式开关时和 topic 一起改为 `True`——否则 T3 骨架会在开关存在之前就打开 Claude 原生联网。
- 2026-09-29：任务排序的理由——T3 改动运行时核心、风险最高，放在 T4（依赖它）之前尽早暴露问题；T5 要加联网模式开关并改 runner 的工具过滤，会碰到运行时和一批既有测试，所以单独成任务而不是并进 T4/T6；前端 T10 需要搬移 `SessionPanel` 等文件，放在 T9（选题池页面）之后，避免两个前端任务互相冲突。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 2026-09-29（起草时的发现，非执行中）：① `ideas` 表、`sessions.project_id` 可空、`StageDefinition.allow_web` 都是 M1 为 M4 预留的，但 `TurnRunner.start_turn` 对 `project_id is None` 直接 `ValueError("M1 只支持属于项目的会话")`，`ToolContext`/`TurnContext` 的 `project_id` 也是必填——无项目会话不是「加一个阶段」就能做，需要 T3 那样动运行时；② `recovery.py` 已经对 `session.project_id` 为空做了保护，说明这条路径当时想过；③ `tests/fixtures/narrative/brief.md` 的事实条目没有「出处」，过不了 T6 的 `check_brief`，M3 的计划里写明了「不需要真的通过」，T6 会更新它；④ 现有 `SessionPicker`/`SessionPanel` 在 `features/workbench`，而头脑风暴抽屉在 `features/ideas`，features 之间不能互相 import，所以 T10 要把它们搬到 `components/session/`。

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无。D1（联网模式开关）和 T13 使用真实 Tavily key 均已在 2026-09-29 获批。

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 无
