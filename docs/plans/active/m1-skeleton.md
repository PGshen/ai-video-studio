# M1：骨架（后端、快照库、运行时、TurnRunner、前端外壳）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | M1 |
| 设计依据 | [架构设计 §2–§4、§6、§7、§9、§10](../../design/2026-09-26-architecture.md)；模块与分层见 [ARCHITECTURE.md](../../ARCHITECTURE.md) |
| 分支 | `m1-skeleton` |
| 批准记录 | 2026-09-27：负责人批准计划（含 Claude 本机登录支持），执行方式为 Subagent-driven |

## 目标

搭好可以独立运行的骨架：在浏览器里创建项目、进入任一阶段，和 agent（Fake / Claude / OpenAI / LiteLLM 模型）对话（Claude 既可用 API key，也可用本机已登录的订阅账号）；agent 改工作区文件后右侧画布实时刷新，每轮自动快照，可以对比、回滚、手动编辑；越界写入会被还原。同时完成风险项 R1–R5 的验证，把结论写进 `references/`。

## 范围

**包含：**

- 后端：`config`、`db`（全部 12 张表 + Alembic 迁移）、`workspace`（快照库、越界检查、上游只读副本、文件读写）、`agent`（事件、`ToolSpec`、运行时协议、阶段定义协议、会话总线、上下文前言、TurnRunner、Fake/Claude/OpenAI 三个适配器、兜底文件工具）、`stages/{topic,narrative,animation}` 的**占位定义**（占位提示词 + §4.3 的可写范围，没有业务工具）、`api`（projects / stages / files / snapshots / sessions + SSE / model-profiles）、`main`。
- 通用的阶段机制：定稿、重新打开、下游 `stale` 标记（§5.4 中与具体阶段无关的部分）。
- 前端：Vite + Vue 3 + TS + Tailwind v4 + shadcn-vue（`dashboard-01` 外壳）+ @ai-elements；项目列表、项目工作台（阶段导航、会话面板、通用文件画布、快照时间线）。
- 质量关口：ruff、pyright、import-linter、pytest；eslint、vue-tsc、vitest；全部接入 `make check`，快速子集接入 `make check-fast`。
- `make dev`（api + 前端）、`make smoke`（真实 key 的冒烟测试）。
- R1–R5 验证。

**不包含：**

- worker 进程和 `jobs` 模块（M2；M1 只建 `jobs` 表）。`make dev` 在 M2 再加入 worker。
- 任何阶段的业务工具、产物 schema、校验器、阶段专属画布（M2–M4）。
- 选题池、头脑风暴、ideas API（M4；M1 只建 `ideas` 表），搜索提供方（M4）。
- 设置页、风格库（M5）。M1 的模型配置通过种子数据 + 只读列表接口提供；`style/STYLE.md` 建项目时写一个占位文件。
- 按镜头 id 的上游变更摘要（M3）；M1 的上游变更摘要是文件级 diff 摘要。
- 用户消息附带图片（接口保留字段，界面 M1 只发文本）。

## 评审关注点

设计没有直接写出、但最容易在真实使用中出问题的五种情况，各自已落到对应任务的测试里：

1. **agent 通过 Shell 删除或改写可写范围外的文件**（包括 `style/`、`upstream/`）→ 本轮结束时被还原，下一轮前言告知。测试在 T4、T6。
2. **用户在 agent 运行中关闭页面或断网后重连** → 用 `after_seq` 续传，不丢事件、不重复。测试在 T8、T12。
3. **工作区里出现二进制文件、空目录、符号链接、`..` 路径** → 快照只收普通文件；二进制文件不生成文本 diff；文件接口拒绝越出工作区的路径和符号链接。测试在 T3、T7。
4. **同一会话连发两条消息 / 超过全局并发** → 第二条返回 409（会话忙）或排队规则明确；不会有两个 turn 同时写同一工作区。测试在 T6、T8。
5. **回滚后 agent 的"记忆"与文件不一致** → 回滚新建快照，下一轮前言写明"已回滚到快照 X"及 diff 摘要。测试在 T6。

## 依赖清单（本计划允许引入的全部依赖）

- 后端运行时：`fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`、`sqlalchemy`（2.x，同步引擎）、`alembic`、`sse-starlette`、`claude-agent-sdk`、`openai-agents[litellm]`。
- 后端开发：`ruff`、`pyright`、`import-linter`、`pytest`、`pytest-asyncio`、`httpx`。
- 前端运行时：`vue`、`vue-router`、`@tanstack/vue-query`、`tailwindcss`、`@tailwindcss/vite`、`codemirror`、`@codemirror/lang-markdown`、`@codemirror/lang-json`、`@codemirror/lang-python`；以及 shadcn-vue CLI 添加 `dashboard-01` 和所用 @ai-elements 组件时**自动写入**的依赖（实际清单记入「决策记录」）。
- 前端开发：`vite`、`@vitejs/plugin-vue`、`typescript`、`vue-tsc`、`vitest`、`@vue/test-utils`、`jsdom`、`eslint`、`eslint-plugin-vue`、`typescript-eslint`、`@vue/eslint-config-typescript`。
- 不引入：SSE 客户端库（自己写基于 fetch 的解析器，约百行，便于测 `after_seq`）、`concurrently`（`make dev` 用 bash 脚本）。

## 冒烟测试预授权（SOP §6 第 7 条）

T15 需要真实 key 和付费调用。**批准本计划即视为同意**：由负责人在 `backend/.env` 中提供 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`（LiteLLM 代表模型），`make smoke` 每次全部用例合计预算上限 **1 美元**（写在测试里，由各运行时的预算机制强制）；整个 M1 期间 `make smoke` 最多运行 5 次。Claude 本机登录用例消耗负责人的订阅额度，不产生 API 费用；负责人已知悉官方文档对第三方产品使用 claude.ai 登录的限制（见 [claude-agent-sdk.md](../../references/claude-agent-sdk.md)），自行判断风险。缺少的 key 对应用例跳过，结论记为"未验证"。

## 验收标准

- [ ] AC1：`make check` 为绿，且包含后端 ruff / pyright / import-linter / pytest、前端 eslint / vue-tsc / vitest、文档检查；`make check-fast` 包含 ruff 和 eslint。（验证：运行命令，贴输出摘要）
- [ ] AC2：import-linter 契约强制 ARCHITECTURE §2 的分层规则 1–5；故意加一条违规 import 时 `make check` 失败。（验证：临时改动 + 输出）
- [ ] AC3：`make setup && make dev` 后，api 监听 `127.0.0.1:8000`，前端监听 `127.0.0.1:5173`；uvicorn reload 只监听 `backend/src`，agent 写工作区文件不会触发重启。（验证：L3，观察日志）
- [ ] AC4：使用 Fake 模型配置，在浏览器中完成：创建项目 → 进入选题阶段 → 发消息 → 看到流式文本和可折叠的工具调用 → 画布出现 agent 写入的文件 → 时间线出现新快照 → 对比 → 回滚 → 手动编辑并保存。（验证：L4 截图，存 `data/evidence/m1/`）
- [ ] AC5：SSE 续传：`curl -N .../stream?after_seq=N` 只回放 seq > N 的已落库事件，然后接实时流。（验证：L3）
- [ ] AC6：越界写入（包括通过 Shell、写入 `upstream/`、改工具托管文件）在本轮结束时被还原，下一轮前言中列出被还原的路径。（验证：L2 契约测试）
- [ ] AC7：用户手动编辑后发下一条消息，先产生 `user_edit` 快照，前言包含 diff 摘要；回滚后前言包含回滚通知。（验证：L2）
- [ ] AC8：一轮的各种结束方式——完成、失败（`partial` 快照）、用户取消、超出预算、进程重启后 `interrupted`——状态和快照都正确，并能"继续"。（验证：L2 + L3 重启 api）
- [ ] AC9：ClaudeRuntime、OpenAIRuntime 用 mock 的 SDK 通过事件转换、业务工具转换（含图片结果）、会话恢复、取消、预算的测试。（验证：L2）
- [ ] AC10：`make smoke` 中 Claude（API key 与本机登录两种方式）、OpenAI（Responses API）、DeepSeek（LiteLLM）各跑通一轮最小对话：写一个文件、调用一个返回图片的业务工具；R1–R5 每项都有结论和证据，不成立的项已按设计 §9 的对策落地；`references/` 相应条目改为 ✅ 或 ❌ 并注明版本和日期。（验证：L5）

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：后端骨架与后端质量关口（完成）

- **目标**：`backend/` 可安装、可启动、可检查。
- **涉及文件**：`backend/pyproject.toml`、`backend/uv.lock`、`backend/.env.example`、`backend/src/studio/{__init__,config,main}.py`、`backend/tests/{conftest,test_config,test_health}.py`、`Makefile`、`scripts/dev.sh`、`docs/runbooks/dev-setup.md`。
- **接口与要点**：
  - Python `>=3.12,<3.13`，uv 管理；`[tool.ruff]`、`[tool.pyright]`（strict 可选，至少 `standard`）、`[tool.pytest.ini_options]`（`asyncio_mode = "auto"`，默认排除 `smoke` 标记）、`[tool.importlinter]` 都写在 `pyproject.toml`。
  - `config.Settings`（pydantic-settings，读 `backend/.env`，前缀 `STUDIO_`）：`data_dir: Path`（默认仓库根下 `data/`）、`host="127.0.0.1"`、`port=8000`、`max_concurrent_turns=2`、`enable_fake_runtime: bool`；`get_settings()`。模型 key 不进 Settings 字段，由模型配置的 `api_key_env` 按名读环境变量。
  - `main.create_app(settings) -> FastAPI`，`GET /api/health` 返回 `{"status": "ok"}`。
  - import-linter 契约先写好 ARCHITECTURE §2 的规则 1–4（模块尚不存在的契约用 `allow_indirect_imports`/在模块出现时生效，具体写法记入决策记录）。
  - `Makefile`：`check-backend` = `ruff check` + `ruff format --check` + `pyright` + `lint-imports` + `pytest`；`check-fast` 加上 `ruff check`；`dev` 调 `scripts/dev.sh`（启动 `uvicorn studio.main:app --reload --reload-dir backend/src`，trap 退出时杀掉子进程）。
- **测试**：`Settings` 默认值与 `STUDIO_DATA_DIR` 覆盖；**`data_dir` 解析后不在 `backend/src` 之下**（在则启动报错）；`/api/health`。
- **完成标准**：`make setup && make check` 为绿；`make dev` 能访问 `/api/health`。
- **验证命令**：`make check`；`make dev` 后 `curl 127.0.0.1:8000/api/health`

### T2：数据库与迁移（完成）

- **目标**：设计 §3.1 的全部表可用，连接配置符合 §7。
- **涉及文件**：`backend/src/studio/db/{__init__,engine,models}.py`、`backend/src/studio/db/migrations/`（Alembic env + `0001_initial`）、`backend/src/studio/db/repo/{projects,stages,sessions,turns,snapshots,profiles}.py`、`backend/tests/db/`。
- **接口与要点**：
  - `make_engine(db_path) -> Engine`：连接时设置 `journal_mode=WAL`、`busy_timeout=5000`、`foreign_keys=OFF`（设计：不设外键）；`session_scope(engine)` 上下文管理器，一次一个短事务。
  - `migrate(engine)`：程序化执行 `alembic upgrade head`，api 启动时调用。
  - 主键统一用字符串 id（`uuid4().hex`，项目用可读 slug 前缀可选），时间用 UTC。JSON 字段用 SQLAlchemy `JSON`。
  - repo 函数只暴露领域操作，返回 Pydantic/dataclass 值对象，不把 ORM 对象泄露出 `db`（规则 5）。本任务只实现 T3–T8 会用到的函数，签名在对应任务中补充。
  - 种子数据：`seed_model_profiles()` 插入 `fake`（仅 `enable_fake_runtime` 时）、`claude-sonnet`（`claude-sonnet-5`，runtime=claude，`api_key_env=ANTHROPIC_API_KEY`）、`claude-login`（同一模型，`api_key_env` 为空＝使用本机 Claude Code 登录）、`gpt`（runtime=openai，Responses）、`deepseek`（runtime=openai，provider=litellm，`api_key_env=DEEPSEEK_API_KEY`），已存在则跳过。具体模型名在 T9/T10 核实后写定。
- **测试**：临时库上 `migrate` 后 12 张表都存在；重复 `migrate` 幂等；PRAGMA 生效；种子幂等。
- **完成标准**：`make check` 为绿。
- **验证命令**：`make check`

### T3：快照库（完成）

- **目标**：实现设计 §3.3 的全部操作。
- **涉及文件**：`backend/src/studio/workspace/{__init__,layout,blobs,snapshot}.py`、`backend/tests/workspace/test_snapshot.py`。
- **接口与要点**：
  - `layout.project_dir(data_dir, project_id) -> Path`；`EXCLUDED_TOP_DIRS = {".cache", "output", "upstream"}`。
  - `BlobStore(root)`：`put(data: bytes) -> str`（sha256，已存在跳过，先写临时文件再原子 rename）、`get(sha) -> bytes`。
  - `scan(workdir) -> dict[str, str]`：相对路径（POSIX 风格）→ sha256；只收普通文件，跳过符号链接和排除目录。
  - `create_snapshot(engine, blobs, project_id, reason, turn_id=None) -> SnapshotRef`，清单与最近一份相同时返回已有快照并标记 `created=False`。
  - `diff(old: Manifest, new: Manifest, blobs) -> WorkspaceDiff`：`added / removed / modified`，文本文件（UTF-8 可解码）附 unified diff，二进制只标记。
  - `rollback(engine, blobs, project_id, target_snapshot_id) -> SnapshotRef`：写回、删除清单外文件（排除目录不动）、清理空目录、新建 `reason=rollback` 快照。
  - `read_file_at(blobs, manifest, path) -> bytes`。
- **测试**：扫描排除规则、符号链接被忽略；去重；增删改 diff；二进制无文本 diff；回滚后内容与目标一致、排除目录不受影响、回滚本身可再回滚；空目录清理。
- **完成标准**：`make check` 为绿。
- **验证命令**：`make check`

### T4：越界检查、上游只读副本、受控文件读写（完成）

- **目标**：设计 §4.3 的权限规则和事后防线；供 api 与兜底工具使用的受控读写。
- **涉及文件**：`backend/src/studio/workspace/{scope,upstream,files}.py`、`backend/tests/workspace/test_{scope,upstream,files}.py`。
- **接口与要点**：
  - `WriteScope(writable: list[str], tool_managed: list[str])`（glob，相对工作区）。`is_writable(scope, relpath) -> bool`：`tool_managed` 永远不可由 agent 写。
  - `guard(workdir, before: Manifest, after: Manifest, scope, blobs, tool_writes: dict[str, str]) -> GuardReport`：还原所有越界的新增/修改/删除到 `before` 的内容；工具托管文件以 `tool_writes`（路径→最后一次工具写入的 sha）为准；返回 `restored: list[str]`。
  - `materialize_upstream(workdir, blobs, sources: dict[stage, Manifest | None])`：清空并重建 `upstream/<stage>/`，只复制该上游阶段的产物目录（如 `topic/`），文件设为只读权限。
  - `files.safe_path(workdir, relpath) -> Path`：拒绝绝对路径、`..`、越出工作区、符号链接；`list_tree`、`read_text`、`write_text(workdir, relpath, content, scope)`（越界抛 `ScopeError`）。
- **测试**：越界新增被删除、越界修改被还原、越界删除被恢复；`upstream/` 的改动不计入快照也不影响还原逻辑（它每轮重建）；工具托管文件被 agent 改写后恢复为工具版本；`safe_path` 的各种非法路径。
- **完成标准**：`make check` 为绿。
- **验证命令**：`make check`

### T5：agent 核心类型、阶段协议、会话总线、FakeRuntime（完成）

- **目标**：运行时无关的核心抽象，以及可编排的测试运行时。
- **涉及文件**：`backend/src/studio/agent/{__init__,events,tools,runtime,stage,bus,fake}.py`、`backend/src/studio/stages/{common,topic,narrative,animation}/`（`__init__.py` + `prompt.md` 占位）、`backend/tests/agent/test_{bus,fake,tools}.py`。
- **接口与要点**：
  - `events`：`TextDelta(text)`、`TextBlock(text)`、`ToolCall(call_id, name, args)`、`ToolResult(call_id, text, images: list[ImageData], is_error)`、`Usage(input_tokens, output_tokens, cost_usd)`、`TurnEnd(resume_ref, status)`；`status ∈ {done, failed, cancelled, budget_exceeded}`，失败时带 `error`。
  - `tools`：`ToolSpec(name, description, input_model: type[BaseModel], stages: set[str], handler)`；`ToolContext(project_id, stage, workdir, record_tool_write)`；`ToolResult(text, images, is_error)`；`invoke_tool(spec, ctx, raw_args) -> ToolResult`（参数校验失败或异常都转成 `is_error=True`）。
  - `runtime`：`TurnContext(system_prompt, user_input: UserInput, tools, workdir, model_profile, resume_ref, cancel_token, budget, write_scope)`；`Budget(max_steps, max_cost_usd)`；`CancelToken`（`asyncio.Event` 包装）；`AgentRuntime` 协议 `run_turn(ctx) -> AsyncIterator[AgentEvent]`；`RuntimeFactory`：按 `model_profile.runtime` 返回实例（claude / openai / fake）。
  - `stage`：`StageDefinition` 协议：`name`、`system_prompt()`、`tools() -> list[ToolSpec]`、`write_scope() -> WriteScope`、`upstream_stages() -> list[str]`、`artifact_dirs() -> list[str]`、`status_summary(workdir) -> str`；`StageRegistry.register/get`。`agent` 不 import `stages`（规则 2）。
  - `stages/*`：三个占位定义，可写范围按 §4.3（topic: `topic/**`；narrative: `narrative/narrative.json`，`tool_managed=["narrative/timing.json"]`；animation: `animation/scenes/**`），上游分别为 `[]`、`["topic"]`、`["narrative"]`。
  - `bus.SessionBus`：`publish(session_id, event)`；`subscribe(session_id) -> AsyncIterator`；订阅者慢时有界队列丢弃**瞬时**事件（text_delta），不丢持久事件。
  - `fake.FakeRuntime(script)`：脚本是步骤列表（`say(text)`、`write(path, content)`、`shell_write(path)`（模拟绕过事前拦截的写入）、`call_tool(name, args)`、`fail(msg)`、`sleep(s)`、`use_cost(usd)`），按步骤产出事件；响应 `cancel_token`。`enable_fake_runtime` 时的默认脚本：回显用户消息并写 `<stage 可写目录>/fake-note.md`，供 AC4 演示。
- **测试**：总线多订阅者、慢订阅者；Fake 脚本各步骤的事件序列；`invoke_tool` 异常转换。
- **完成标准**：`make check` 为绿（含 import-linter 规则 2、3）。
- **验证命令**：`make check`

### T6：TurnRunner 与上下文前言（完成）

- **目标**：设计 §4.4 的完整一轮生命周期，用 FakeRuntime 端到端测试。
- **涉及文件**：`backend/src/studio/agent/{runner,preamble,stage_flow}.py`、`backend/src/studio/db/repo/{turns,sessions}.py`（补充）、`backend/tests/agent/test_{runner,preamble,stage_flow}.py`。
- **接口与要点**：
  - `TurnRunner(engine, blobs, registry, runtime_factory, bus, settings)`；`start_turn(session_id, user_input) -> turn_id`（会话已有运行中的 turn → `SessionBusyError`；超过全局并发 → turn 进入 `queued`，按 FIFO 启动）；`cancel(turn_id)`；`recover_on_startup()`（§4.4 第 8 步）。
  - 一轮步骤：检测变化 → `user_edit` 快照 → 刷新 `upstream/`（读各上游的 `finalized_snapshot_id`）→ 构建前言 → `run_turn` → 事件处理（持久事件分配**会话内单调递增的 `seq`** 后落库再发布；`TextDelta` 只发布；文件类工具调用后发布 `workspace_changed`）→ 结束：`guard` → 快照（`turn`，失败为 `partial`）→ 写 turn 状态、用量、成本、`end_snapshot_id` → 发布 `turn_status`。任何异常路径也必须先快照再改状态（§7）。
  - 预算：步数（工具调用次数）或成本超限 → 触发取消 → 状态 `budget_exceeded`。
  - `preamble.build_preamble(...) -> str`：用户手动修改（文件列表 + 截断的 diff）、上游新定稿（文件级 diff 摘要）、上一轮被还原的路径、回滚通知、阶段 `status_summary`、新会话的交接摘要（阶段产物文件清单）。没有内容时返回空串。
  - 定稿的通用逻辑也放在这里旁边的 `agent/stage_flow.py`：`finalize(project_id, stage)`、`reopen(project_id, stage)`、下游 `stale` 标记与下游一轮结束后恢复 `active`（§5.4）。
- **测试**（全部用 FakeRuntime + 临时数据目录）：正常一轮的事件落库与快照；`seq` 连续；失败 → `partial`；取消；预算超限；shell 越界写入被还原且下一轮前言列出（评审关注点 1）；写入 `upstream/` 被还原（R5）；用户编辑 → `user_edit` 快照 + 前言 diff；回滚 → 前言通知（评审关注点 5）；会话忙 409 / 全局并发排队（评审关注点 4）；启动恢复 `running → interrupted`；定稿、重新打开、stale 流转。
- **完成标准**：`make check` 为绿。
- **验证命令**：`make check`

### T7：API——项目、阶段、文件、快照、模型配置（待开始）

- **目标**：非会话类接口。
- **涉及文件**：`backend/src/studio/api/{__init__,deps,schemas,projects,files,snapshots,profiles}.py`、`backend/src/studio/main.py`、`backend/tests/api/`。
- **接口与要点**（前缀 `/api`）：
  - `POST /projects {title, settings?}`：建库行、初始化工作区（`style/STYLE.md` 占位）、`init` 快照、`project_stages` 三行（topic=`active`，其余 `locked`）；`GET /projects`、`GET /projects/{id}`（含各阶段状态）。
  - `POST /projects/{id}/stages/{stage}/finalize`、`POST .../reopen`。
  - `GET /projects/{id}/files`（树）、`GET /projects/{id}/files/{path:path}`、`PUT /projects/{id}/files/{path:path}?stage=`（按该阶段的 `write_scope` 检查，越界 403；有运行中的 turn 时 409）。
  - `GET /projects/{id}/snapshots`、`GET /projects/{id}/snapshots/diff?from=&to=`、`POST /projects/{id}/snapshots/{sid}/rollback`（有运行中的 turn 时 409）。
  - `GET /model-profiles`（不返回 key，只返回 key 是否已配置）。
  - `main` 的 lifespan：`migrate` → 种子 → 注册三个阶段 → `recover_on_startup`。
- **测试**：httpx `AsyncClient` + 临时数据目录；非法路径 400、符号链接拒绝（评审关注点 3）；越界 PUT 403；运行中 409。
- **完成标准**：`make check` 为绿；`/docs` 能看到全部接口。
- **验证命令**：`make check`

### T8：API——会话、消息、SSE（待开始）

- **目标**：对话接口与流式推送。
- **涉及文件**：`backend/src/studio/api/sessions.py`、`backend/tests/api/test_sessions.py`、`backend/tests/api/test_stream.py`。
- **接口与要点**：
  - `POST /projects/{id}/stages/{stage}/sessions {model_profile_id}`（新会话设为 `is_active`，旧会话取消活动）；`GET .../sessions`；`GET /sessions/{id}`（含 turns 列表和状态）。
  - `POST /sessions/{id}/messages {text}` → `202 {turn_id}`；会话忙 409。`POST /sessions/{id}/cancel`；`POST /sessions/{id}/continue`（对 `interrupted`/`budget_exceeded` 发一条"继续"消息）。
  - `GET /sessions/{id}/stream?after_seq=`（sse-starlette）：先回放 `seq > after_seq` 的已落库事件（SSE `id` = seq），再接总线实时事件；瞬时事件没有 `id`；回放与实时交界处按 seq 去重。
  - SSE 事件类型：`text_delta`、`text`、`tool_call`、`tool_result`、`snapshot`、`notice`、`error`、`workspace_changed`、`turn_status`。
- **测试**：Fake 一轮的完整事件流；中途断开后用 `after_seq` 重连不丢不重（评审关注点 2）；会话忙 409。
- **完成标准**：`make check` 为绿；手动 `curl -N` 可看到流。
- **验证命令**：`make check`

### T9：ClaudeRuntime（待开始）

- **目标**：Claude Agent SDK 适配器，mock 测试覆盖。
- **涉及文件**：`backend/src/studio/agent/claude_runtime.py`、`backend/tests/agent/test_claude_runtime.py`、`docs/references/claude-agent-sdk.md`。
- **第一步（核实）**：阅读已安装 `claude-agent-sdk` 的源码和官方文档，逐条核实 references 中 ⚠️ 的条目（选项字段、`@tool`/`create_sdk_mcp_server`、消息类型与累计用量、image content block、`PreToolUse` hook、sandbox 选项、会话存储位置、`ClaudeSDKClient.interrupt()`），能从源码确认的改为 ✅ 并注明版本和日期；需要真实调用才能确认的留给 T15。
- **接口与要点**：
  - **认证方式**：模型配置的 `api_key_env` 有值 → 从该环境变量读 key 注入 `env`；为空 → 本机登录模式：不注入 key，并从传给子进程的环境中**移除** `ANTHROPIC_API_KEY`（否则会覆盖登录凭据），且不改 `CLAUDE_CONFIG_DIR`（会话存储的处理见 R4）。本机登录模式下 `total_cost_usd` 只是估算，成本预算仅作参考，步数上限照常强制；turn 的 `usage` 中标记 `auth=login`。
  - 用 `ClaudeSDKClient`（为了 `interrupt()`）；选项：`model`、`cwd=workdir`、`setting_sources=[]`、`permission_mode="acceptEdits"`、内置工具 Read/Write/Edit/Glob/Grep/Bash（brainstorm/topic 阶段另加 WebSearch/WebFetch，M1 按阶段定义开关）、业务工具经 `create_sdk_mcp_server` 转换（`ToolResult.images` → image content block）、`resume=resume_ref`、`env` 注入 key、会话存储指向 `data/claude/`（方式以核实结果为准）。
  - `PreToolUse` hook：Write/Edit 的目标路径不满足 `write_scope` → 拒绝并说明原因；sandbox 按核实结果开启。
  - 事件转换：流式文本 → `TextDelta`，完整文本块 → `TextBlock`，tool_use / tool_result → `ToolCall`/`ToolResult`，result 消息 → `Usage`（按会话减去之前的累计值）+ `TurnEnd(resume_ref=session_id)`。
  - 预算：成本/步数超限时 `interrupt()`。
- **测试**：两种认证方式下传给 SDK 的 `env` 是否正确（登录模式下不含 `ANTHROPIC_API_KEY`）；用假的 SDK 客户端（按消息序列回放）测试事件转换、累计用量差值、图片结果转换、hook 拒绝越界、取消调用 `interrupt()`、预算超限。
- **完成标准**：`make check` 为绿；references 已更新。
- **验证命令**：`make check`

### T10：OpenAIRuntime 与兜底文件工具（待开始）

- **目标**：OpenAI Agents SDK 适配器（Responses API 与 LiteLLM 两条路径），mock 测试覆盖。
- **涉及文件**：`backend/src/studio/agent/{openai_runtime,apply_patch,fallback_tools}.py`、`backend/tests/agent/test_{openai_runtime,apply_patch,fallback_tools}.py`、`docs/references/openai-agents-sdk.md`、`docs/references/legacy-assets.md`。
- **第一步（核实）**：阅读已安装 `openai-agents` 的源码，核实 `ApplyPatchTool`/`ApplyPatchEditor` 接口、`ShellTool` 本地 executor 接口、`FunctionTool` 与 `ToolOutputImage`、`SQLiteSession`、`LitellmModel`、`RunHooks`、流式事件类型、取消方式；在 references 注明版本号。
- **接口与要点**：
  - 模型选择：`provider=openai` → `OpenAIResponsesModel`，原生 `ApplyPatchTool` + `ShellTool`（工作目录为工作区）；`provider=litellm` → `LitellmModel`，兜底文件工具集，不提供 Shell（R1 的结论可能改变这一点，见 T15）。
  - `apply_patch.WorkspaceApplyPatchEditor`：落盘通过 `workspace.files.write_text`（规则 6），越界返回错误。
  - `fallback_tools`：`list_files`、`read_file`、`write_file`、`edit_file`，从旧项目 `OpenAICodegenWorkspace` **复制后改写**为 `ToolSpec`，底层用 `workspace.files`；迁移对应测试；更新 legacy-assets 状态。
  - 业务工具 → `FunctionTool`；图片结果 → `ToolOutputImage`（R2 不成立时的对策在 T15 落地）。
  - 会话：`SQLiteSession(session_id, data_dir/"openai_sessions.db")`，只保留最近 N 轮（N 写进配置）。
  - 预算：`RunHooks.on_llm_end` 累计用量，按模型配置价格算成本，超限取消；取消：取消运行中的 task，状态 `cancelled`。
- **测试**：用假的模型（SDK 提供的测试模型或 mock `Model` 接口）驱动：事件转换、工具调用、图片结果、预算、取消；`WorkspaceApplyPatchEditor` 的增删改与越界；兜底工具迁移过来的测试。
- **完成标准**：`make check` 为绿；references 与 legacy-assets 已更新。
- **验证命令**：`make check`

### T11：前端骨架与前端质量关口（待开始）

- **目标**：`frontend/` 可安装、可启动、可检查，外壳就位。
- **涉及文件**：`frontend/`（Vite 工程、`src/main.ts`、`src/router.ts`、`src/App.vue`、`components.json`、`src/components/ui/`、`src/components/ai-elements/`、`eslint.config.ts`、`vitest` 配置）、`Makefile`、`scripts/dev.sh`、`docs/references/frontend-stack.md`。
- **接口与要点**：
  - pnpm；Tailwind v4 用 `@tailwindcss/vite` 与 CSS 中的 `@import "tailwindcss"`；`npx shadcn-vue@latest init` + `add dashboard-01`；@ai-elements 组件（registry `https://registry.ai-elements-vue.com/{name}.json`）按需添加：conversation、message、prompt-input、tool、code-block（以实际可用名称为准）。
  - 路由：`/projects`、`/projects/:id/:stage`；`/ideas`、`/settings` 放占位页。
  - Vite dev server 代理 `/api` 到 `127.0.0.1:8000`，绑定 `127.0.0.1:5173`。
  - ESLint：`no-restricted-imports` 实现 ARCHITECTURE §3 的规则（`features/*` 互不 import；`components/` 不 import `features/`）；`components/ui`、`components/ai-elements` 排除部分格式规则（生成代码尽量不手改）。
  - `Makefile`：`check-frontend` = `eslint` + `vue-tsc --noEmit` + `vitest run`；`check-fast` 加 `eslint`；`dev.sh` 同时启动前端。
  - 把实际的组件清单、Tailwind v4 配置方式写进 `frontend-stack.md`（✅ + 日期）。
- **测试**：路由解析的 vitest；一条故意违规的 import 让 eslint 失败（验证后删除，记录到验证记录）。
- **完成标准**：`make check` 为绿；`make dev` 能打开外壳页面。
- **验证命令**：`make check`

### T12：前端 API 客户端与 SSE 客户端（待开始）

- **目标**：类型化的 HTTP 客户端和支持续传的 SSE 客户端。
- **涉及文件**：`frontend/src/api/{http,sse,endpoints}.ts`、`frontend/src/types/`、`frontend/src/composables/{useSessionStream,queries}.ts`、对应 `*.spec.ts`。
- **接口与要点**：
  - `types/`：手写与后端 `api/schemas.py` 对应的类型（M1 不引入代码生成）。
  - `sse.ts`：`openStream(url, {afterSeq, onEvent, signal})`，基于 `fetch` + `ReadableStream` 解析 SSE（`id`/`event`/`data`、多行 data、注释行、分块边界）；断线后指数退避重连，带上最后收到的 seq。
  - `useSessionStream(sessionId)`：维护消息列表（合并 `text_delta` 为进行中的文本块，`text` 到达时替换）、工具调用（`tool_call` 与 `tool_result` 按 `call_id` 配对）、turn 状态；收到 `workspace_changed` 时让文件查询失效。
  - `queries.ts`：TanStack Query hooks（projects、files、snapshots、sessions、model-profiles）及其 mutation。
- **测试**：SSE 解析（跨 chunk 边界、多行 data、无 id 的瞬时事件）；重连携带 `after_seq` 且不重复（评审关注点 2）；`useSessionStream` 的增量合并与配对。
- **完成标准**：`make check` 为绿。
- **验证命令**：`make check`

### T13：工作台——项目列表、阶段导航、会话面板（待开始）

- **目标**：能在浏览器中创建项目并对话。
- **涉及文件**：`frontend/src/features/projects/`、`frontend/src/features/workbench/{WorkbenchPage,StageNav,SessionPanel,SessionPicker}.vue`、对应 spec。
- **接口与要点**：
  - 项目列表页：列表 + 新建对话框（标题）。
  - 工作台顶部：阶段导航（`locked` 灰、`active`、`finalized ✓`、`stale ⚠`），[定稿] 按钮（M1 无阶段条件，直接调用 finalize，需二次确认）。
  - 会话面板：模型配置下拉 + [新会话]；消息流用 @ai-elements Conversation/Message，工具调用用 Tool（可折叠）；输入框 PromptInput；[停止]（运行中）/[继续]（`interrupted`、`budget_exceeded`）；错误和 turn 状态提示。
- **测试**：组件级 vitest 只测状态逻辑（例如按钮可用性随 turn 状态变化）；界面在 T15 前用浏览器手动验证并截图。
- **完成标准**：`make check` 为绿；Fake 配置下能在浏览器完成一轮对话。
- **验证命令**：`make check`；浏览器 L4

### T14：工作台——通用文件画布与快照时间线（待开始）

- **目标**：画布与时间线，完成 AC4 的全部交互。
- **涉及文件**：`frontend/src/features/canvas/generic/{FileCanvas,FileTree,CodeEditor}.vue`、`frontend/src/features/workbench/SnapshotTimeline.vue`、对应 spec、`.claude/launch.json`。
- **接口与要点**：
  - 文件树（隐藏 `.cache/`、`output/`；`upstream/` 显示为只读分组）+ CodeMirror 6 编辑器（按扩展名选 markdown/json/python 语言包）；agent 运行时只读；保存调用 PUT，403/409 给出提示。
  - `workspace_changed` 触发文件树与当前文件重新拉取；当前文件有未保存修改时提示冲突而不是直接覆盖。
  - 快照时间线：按时间列出（原因、所属 turn），选两个快照 [对比]（CodeBlock 显示 unified diff），[回滚到此]（二次确认）。
  - `.claude/launch.json` 写好 `frontend` 与 `api` 两个配置，供 L4 验证使用。
- **测试**：编辑器只读状态与未保存冲突逻辑的 vitest；AC4 的浏览器走查截图存 `data/evidence/m1/`。
- **完成标准**：`make check` 为绿；AC4 走查通过。
- **验证命令**：`make check`；浏览器 L4

### T15：冒烟测试与 R1–R5 验证（待开始）

- **目标**：真实模型跑通三种接入方式，给出 R1–R5 的结论并落地对策。
- **涉及文件**：`backend/tests/smoke/`、`Makefile`（`smoke` 目标：`pytest -m smoke`）、`docs/references/{claude-agent-sdk,openai-agents-sdk}.md`、`docs/runbooks/verification.md`（按实际更新）。
- **接口与要点**：
  - 测试专用业务工具 `smoke_image`：返回一句文字和一张小 PNG（测试数据内置）。
  - 每种运行时一个用例（Claude 两种认证方式各一个）：一轮对话中要求模型写 `topic/smoke.md` 并调用 `smoke_image`，断言文件存在、工具结果被模型看到（要求模型复述图片中的颜色/文字）、turn 状态 `done`、成本在预算内。预算见「冒烟测试预授权」。
  - R1：DeepSeek（LiteLLM）上尝试 `ApplyPatchTool`/`ShellTool`；不可用 → 确认 LiteLLM 路径自动使用兜底工具集（T10 已是默认），记录结论。
  - R2：LiteLLM 模型的图片工具结果；不可用 → 实现"文本说明 + 图片作为下一条输入消息"的对策，按模型配置 `supports_vision` 和运行时决定。
  - R3：macOS 上手动验证 Claude sandbox 对 Bash 写工作区外文件的限制；不符 → 关闭 Bash，依赖事后防线。
  - R4：验证 Claude 会话存储能否指向 `data/claude/`；不能 → 接受默认位置并在 dev-setup 中说明。同时验证它与本机登录模式的关系：若指向数据目录会导致读不到登录凭据，则登录模式下使用默认位置，API key 模式下使用数据目录，结论写进 references。
  - 本机登录：用 `claude-login` 配置跑一轮最小对话，确认不设 key 时能以订阅账号完成，记录 `total_cost_usd` 的表现。
  - R5：真实模型下读取 `upstream/` 后是否尝试写入，结合 T6 的契约测试给出结论。
- **测试**：即上述冒烟用例（默认不在 `make check` 中）。
- **完成标准**：AC10 满足；每项风险的结论写进「验证记录」和 references。
- **验证命令**：`make smoke`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-09-27 — T1：后端骨架与后端质量关口 — 完成，`make check`/`make setup`/`make dev` 均验证通过（见本提交）。
- 2026-09-27 — T2：数据库与迁移 — 完成，`make check` 全绿（见本提交）。
- 2026-09-27 — T3：快照库 — 完成，`make check` 全绿（见本提交）。
- 2026-09-27 — T4：越界检查、上游只读副本、受控文件读写 — 完成，`make check` 全绿（见本提交）。
- 2026-09-27 — T5：agent 核心类型、阶段协议、会话总线、FakeRuntime — 完成，`make check` 全绿（含新增的 import-linter 规则 2、3）（见本提交）。
- 2026-09-27 — T6：TurnRunner 与上下文前言 — 完成，`make check` 全绿（审查修复后 205 个测试）；`runner.py` 约 516 行，超出预期的 400 行，未自行拆分，交控制者决定（见本提交）。

## 下一步

- 从 T7 开始：API——项目、阶段、文件、快照、模型配置。T7 创建项目时用 `repo.stages.create_stage` 建三行阶段状态；定稿/重新打开调用 `agent.stage_flow.finalize/reopen`（`StageFlowError` → 409）；文件 PUT 和回滚在 `TurnRunner.is_project_busy(project_id)` 为真时返回 409。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-09-26 — SQLAlchemy 使用同步引擎，异步代码中直接调用短事务 — 单人本地、SQLite 写操作毫秒级；避免引入 aiosqlite 和异步 ORM 的复杂度。
- 2026-09-26 — SSE 的 `after_seq` 指会话内单调递增的 `turn_events.seq`，瞬时事件不带 seq、不回放 — 设计要求续传，但没规定 seq 的作用域；会话级最方便前端续传。
- 2026-09-26 — M1 不实现 worker 和 `jobs` 模块，只建表 — 设计 §10 把 worker 成片放在 M2。
- 2026-09-26 — 三个阶段在 M1 注册占位定义（占位提示词 + §4.3 可写范围）— 让通用画布和越界检查能在真实阶段配置下端到端验证，同时不越过 `agent` 不 import `stages` 的规则。
- 2026-09-26 — 自己实现 fetch SSE 客户端，不引入库 — 逻辑小，且续传语义需要完全可控、可测。
- 2026-09-27 — Claude 同时支持本机登录：用模型配置 `api_key_env` 为空表示登录模式，不新增表字段 — 负责人要求；复用设计 §3.1 已有字段，不偏离设计。
- 2026-09-26 — 定稿、重新打开、stale 流转的通用部分放进 M1 — 上游只读副本（§4.3、R5）依赖定稿快照，没有定稿就无法验证。
- 2026-09-27 — T1：锁定依赖版本（`uv sync` 解析结果，见 `backend/uv.lock`）：Python `3.12.11`（uv 自动下载）、`fastapi 0.141.1`、`uvicorn 0.54.0`（含 `standard` extras：`httptools`、`uvloop`、`watchfiles`、`websockets` 等）、`pydantic 2.13.5`、`pydantic-settings 2.15.0`；开发依赖 `ruff 0.16.9`、`pyright 1.1.414`、`import-linter 2.15`、`pytest 8.4.2`、`pytest-asyncio 0.26.0`、`httpx 0.28.1`。
- 2026-09-27 — T1：import-linter 契约按控制者裁定 R1 只写"`config` 不 import `main`"一条最小契约（此时只有这两个模块存在）；后续任务新建 `db`/`workspace`/`agent`/`stages`/`api`/`worker` 时，把 ARCHITECTURE §2 对应的规则 1–6 逐条补进 `backend/pyproject.toml` 的 `[tool.importlinter]`。
- 2026-09-27 — T1：`Settings.data_dir` 用 pydantic `field_validator` 解析为绝对路径并校验不落在 `backend/src` 之下，校验失败抛自定义 `WorkspaceInsideSourceError`（继承 `RuntimeError`，不是 `ValueError`）——pydantic v2 只把 `ValueError`/`TypeError`/`AssertionError` 包装成 `ValidationError`，用独立异常类型能让调用方精确捕获这一种配置错误，而不必解析 pydantic 的通用校验错误。
- 2026-09-27 — T1：测试中不传 `_env_file=None` 覆盖 `Settings`（pyright 对 pydantic-settings 的 dataclass-transform 合成 `__init__` 不认识这个私有 kwarg，会报 `reportCallIssue`）；改为直接传字段值（如 `data_dir=...`）覆盖，init kwargs 在 pydantic-settings 的来源优先级里本就高于 `.env` 文件，效果等价且类型检查干净。
- 2026-09-27 — T1：给 `scripts/check_docs.py` 的 `SKIP_DIRS` 加入 `.superpowers`（本次 SDD 编排的临时脚手架目录，已在 `.gitignore` 中，不属于文档知识库）——运行 `make check` 时发现该目录下的 `common.md` 引用了尚未创建的 `docs/references/claude-agent-sdk.md`（T9 才会创建），导致 `check-docs` 误报，与 T1 范围无关但阻塞了质量关口，遂一并修正扫描范围。
- 2026-09-27 — T2：`turn_events` 冗余存一份 `session_id`（可从 `turn_id` 关联 `turns.session_id` 推出）——`seq` 的作用域是会话级（见 2026-09-26 决策），SSE `after_seq` 续传按会话查询时直接按 `(session_id, seq)` 走索引，不必联表 `turns`；索引 `ix_turn_events_session_seq` 建在 `(session_id, seq)` 上。
- 2026-09-27 — T2：`model_profiles` 种子的 `provider` 字段取值——`claude-sonnet`/`claude-login` 用 `anthropic`，`gpt` 用 `openai`，`deepseek` 用 `litellm`（区分"经 LiteLLM 转发"和"原生 OpenAI Responses API"两条 T10 要分别实现的路径）；`fake` 用 `provider="fake"`。这些是本任务的临时值，T9/T10 核实运行时行为后可能调整。
- 2026-09-27 — T2：本任务只在 `repo/` 下创建 `projects.py`、`profiles.py` 两个文件（各自的仓储函数与测试），未创建 `stages.py`/`sessions.py`/`turns.py`/`snapshots.py` 空文件——遵循"先写失败测试再实现"和 YAGNI，这几个仓储会分别在 T6（`turns`/`sessions`）、T3/T7（`snapshots`）、T7（`stages`）按各自任务需要的签名新增，brief 中列出的文件名是完整清单，不代表本任务要全部建好空壳。
- 2026-09-27 — T2：import-linter 新增两条契约（规则 5 相关）——`config` 不依赖 `db`（config 层依赖表里 config 一行是"—"）；`main` 不 import `studio.db.models`（只有 `db` 定义 ORM 模型，其他模块经 `db.repo` 的函数拿到 dataclass 值对象）。
- 2026-09-27 — T3：`create_snapshot`/`rollback` 的签名（`engine, blobs, project_id, ...`）不带 `data_dir`/`workdir` 参数，工作区目录从 `blobs.root.parent` 反推（约定 `<data_dir>/blobs/` 与 `<data_dir>/projects/<id>/` 是同一 `data_dir` 下的兄弟目录）——避免在这两个函数上额外增加参数，调用方（T4/T6）只需持有同一个 `BlobStore` 实例即可；`scan`/`read_file_at` 保持纯函数（不依赖这一约定），方便单独测试。
- 2026-09-27 — T3：新增两条 import-linter 契约——`workspace` 不直接依赖 `studio.db.models`（`allow_indirect_imports = true`，因为 `workspace` 经 `studio.db.repo.snapshots` 间接用到 `db.models` 是被允许的合法路径，只禁止绕过 repo 直接 import 模型）；`workspace` 不依赖 `main`。
- 2026-09-27 — T3：`rollback` 内部复用 `create_snapshot`（而不是直接插入快照行）——回滚后的工作区状态和"新建快照"的语义完全一致（含清单去重：目标已是最新时 `created=False`），复用能保证这条规则不必在两处分别实现。
- 2026-09-27 — T4：`is_writable` 的 glob 匹配直接用标准库 `fnmatch.fnmatchcase`，不额外实现 `**` 语义——Python 3.12 没有 `PurePosixPath.full_match`（3.13 才有），而 `fnmatch` 把 `*` 翻译成正则 `.*`（本就跨越 `/`），所以 `topic/**` 天然匹配 `topic/` 下任意深度的文件，没有通配符的模式要求完全相等；已用测试验证 `**` 语义符合预期，不需要自己写匹配器。
- 2026-09-27 — T4：路径包含性检查（`(workdir / relpath).resolve()` 后确认仍在 `workdir` 内）从 `snapshot._safe_dest` 提炼成 `layout.resolve_relpath`（抛 `PathEscapesWorkdir`），`snapshot._safe_dest` 和 `files.safe_path` 都复用它，各自包一层转换成调用方期望的异常类型（`ValueError` / `ScopeError`）——避免同一段"越界检查"逻辑在两处重复实现和分别测试。
- 2026-09-27 — T4：`guard` 除了按 `before`/`after`/`tool_writes` 还原越界改动外，额外扫描并删除工作区里排除目录（`EXCLUDED_TOP_DIRS`）之外的所有符号链接（控制者裁定）——`scan()` 天然忽略符号链接，如果 `guard` 不清理，agent 建的符号链接会一直留在工作区（不进快照、不受越界检查约束），可能被用作绕过下一轮检查的手段；删除的符号链接路径计入 `GuardReport.restored`。
- 2026-09-27 — T4：`snapshot._data_dir_of` 增加防御性检查，`blobs.root.name != "blobs"` 时抛 `ValueError`（控制者裁定）——`_data_dir_of` 靠"约定" `<data_dir>/blobs/` 反推 `data_dir`，这个假设一旦被调用方传错（例如误传了别的目录当 `BlobStore.root`）会静默算出错误的工作区路径，进而让 `create_snapshot`/`rollback` 操作到错误的位置；提前失败比静默算错更安全。
- 2026-09-27 — T4：`materialize_upstream` 的 `sources[stage]` 约定为该阶段定稿快照的**完整清单**（可能含 `style/` 等其他路径），函数内部按 `<stage>/` 前缀过滤后再落盘到 `upstream/<stage>/`——这样调用方（T6 的 TurnRunner）不需要预先按目录切分清单，直接把定稿快照的 manifest 传进来即可，防御性地保证只有属于该阶段产物目录的文件被物化。
- 2026-09-27 — T5（审查后修正，替换本条最初的版本——最初版本在"队列全是持久事件"时会退化为丢弃最旧的一条持久事件，审查认定这违反"持久事件永不丢失"的要求，已修正）：`SessionBus` 每个订阅者内部拆成两条队列——瞬时事件（`text_delta`/`workspace_changed`/`turn_status`）走一条有界队列（容量 `queue_size`），写满时丢弃队列里最旧的一条瞬时事件腾位置（滑动窗口，只保留最新的一批）；持久事件走一条完全无界的队列，永远接受新事件，不做任何容量检查，因此**不可能**被丢弃。两条队列靠 `publish` 时打上的总线全局单调递增内部序号合并成一条有序的事件流（`_Subscriber.pump`：总是从两条队列队首里选内部序号更小的先产出），保证"瞬时事件和持久事件之间的相对到达顺序"在没有事件被丢弃时尽量保持；`publish` 本身是纯同步的入队操作，不阻塞、不抛异常。测试改为验证"发布远超队列容量的持久事件，全部一条不少地送达"，以及跨类型的顺序合并。
- 2026-09-27 — T5：`SessionBus.subscribe` 的注册（把队列加进 `_subscribers`）必须在**同步**代码里完成，不能写在 `async def` 生成器函数体内——`async def` 生成器函数体在第一次 `__anext__()` 之前完全不执行，如果注册逻辑在里面，`subscribe()` 调用后、订阅者第一次迭代前发布的事件会因为队列还没登记而丢失。拆成同步的 `subscribe()`（创建队列、登记、返回一个独立的异步生成器）+ `_pump()`（只负责从队列取事件、`finally` 里注销）解决；`subscribe` 的返回类型标注为 `AsyncGenerator` 而不是 `AsyncIterator`，因为调用方（T6/T8 的 SSE 端点、测试）需要在断开连接时调用 `aclose()` 主动触发注销。
- 2026-09-27 — T5：`fake.shell_write(path, content="")` 模拟 Shell 类原生工具绕过事前拦截的写入，直接调用新增的 `workspace.files.write_text_unscoped`（只做 `safe_path` 的路径安全校验，不检查 `WriteScope`）——设计 §4.3 里 Shell 的越界写入本就只靠回合结束时的 `scope.guard` 事后兜底，`FakeRuntime` 需要一种"跳过事前拦截"的写入方式来让 T6 能测试这条防线；没有复用 `write_text`（会因为越界而抛 `ScopeError`），而是在 `workspace` 模块（唯一读写工作区文件的模块，规则 6）里新增一个显式跳过范围检查的函数，供 `fake.py` 调用，避免在 `agent` 里绕过 `workspace` 直接操作文件系统。
- 2026-09-27 — T5（审查后修正，替换本条最初的版本——最初版本给 `FakeRuntime` 加了 `project_id`/`stage`/`record_tool_write` 三个可选构造参数，审查认定这些本质是"运行时执行一轮时需要的上下文"，不该绑在某一个运行时实现的构造函数上，已改成 `TurnContext` 的字段）：`TurnContext`（设计 §4.1）新增 `project_id: str`、`stage: str`、`record_tool_write: Callable[[str, str], None]` 三个字段，和 `tools.ToolContext` 的对应字段一一对应。选择直接扩展 `TurnContext`、而不是另外引入一个 `make_tool_context(ctx, ...)` 工厂函数——`TurnRunner`（T6）构造 `TurnContext` 时本来就持有这些值，一并传入最直接；运行时（`FakeRuntime`/`ClaudeRuntime`/`OpenAIRuntime`）需要给业务工具构造 `ToolContext` 时直接从 `ctx.project_id`/`ctx.stage`/`ctx.workdir`/`ctx.record_tool_write` 取，不用再各自决定"这几项从哪来"。`FakeRuntime` 的构造函数因此收窄回 `FakeRuntime(script: list[FakeStep] | None = None)`。
- 2026-09-27 — T5（审查后新增，控制者裁定 R2 的落地）：`RuntimeFactory` 本身仍然只是纯注册表，不预置任何注册；`fake` 运行时的注册逻辑放进 `studio.agent.fake.register_fake(factory)`（并从 `studio.agent` 包一并导出），内部就是 `factory.register("fake", FakeRuntime)`——`FakeRuntime` 类本身现在满足零参数构造（`script=None`），`run_turn` 在拿到当轮的 `ctx` 之后才用 `default_fake_script(ctx.write_scope, ctx.user_input.text)` 现场生成默认脚本，而不是构造时就固定死，这样"注册一个不带脚本、每轮都正确回显当轮用户消息"的 `fake` 运行时"才能同时满足 `RuntimeConstructor = Callable[[], AgentRuntime]` 的签名。`main`（T7 之后）在 `settings.enable_fake_runtime` 为真时调用 `register_fake`。
- 2026-09-27 — T5：`FakeRuntime` 按脚本步数（不区分步骤类型）和累计 `use_cost` 总额分别检查 `ctx.budget.max_steps`/`max_cost_usd`，超限时提前产出 `TurnEnd(status="budget_exceeded")` 并停止——`Budget` 字段在设计 §4.1 就存在，`TurnStatus` 也包含 `budget_exceeded`，作为测试运行时如果完全不响应预算配置，T6 就没有办法用 `FakeRuntime` 测试 TurnRunner 的预算超限路径；真实运行时按步数/成本判断超限的具体时机由 T9/T10 决定。
- 2026-09-27 — T5：`agent.tools.ToolHandler` 的参数类型标注用 `Any` 而不是 `BaseModel`——`Callable` 的参数位置是逆变的，如果标成 `Callable[[ToolContext, BaseModel], ...]`，任何接受更具体子类型（例如 `_EchoArgs`）的 handler 函数赋值给 `ToolSpec.handler` 时都会被 pyright 判定类型不兼容（`ToolSpec` 要放进同一个 `list[ToolSpec]`，各自的 `input_model` 不同，静态类型没法逐个精确标注）；运行时的实际类型安全由 `invoke_tool` 里的 `spec.input_model.model_validate` 保证。
- 2026-09-27 — T5：本任务除了简报「涉及文件」里列出的 `tests/agent/test_{bus,fake,tools}.py`，还补充了 `tests/agent/test_{runtime,stage}.py` 和 `tests/stages/test_placeholders.py`——`CancelToken`、`RuntimeFactory`、`StageRegistry`、三个阶段占位定义的可写范围/上游/产物目录都是简报里写了精确值、但仅靠 `test_bus`/`test_fake`/`test_tools` 不会被直接测到的逻辑（`test_fake` 只经三个阶段的 `write_scope()` 间接用到占位定义，不校验它们自身的字段），按"测试先行"的项目约定为它们各自补了最小单测；同时给新增的 `workspace.files.write_text_unscoped` 补了 `tests/workspace/test_files.py::TestWriteTextUnscoped`。这些都是新增测试文件，不算改变已完成任务（T1–T4）的范围。
- 2026-09-27 — T6：`turn_events.seq` 在插入事件的同一个短事务里按"会话内 max+1"分配（`repo.turns.append_event`），不用内存计数器；新增迁移 0002 把 `(session_id, seq)` 索引改为唯一索引作为兜底 — 单进程、同步短事务（事务内无 await）不会撞号；重启后不需要初始化计数器。
- 2026-09-27 — T6：**同一项目同时只运行一个 turn**（不同阶段的会话也一样），多出的 turn 保持 `queued`，和全局并发上限一起按 FIFO 调度（跳过被项目占用阻塞的 turn，后面其他项目的 turn 可以先启动）— 各阶段共用一个工作区，两个 turn 并行时，一方的越界检查会把另一方的合法写入当成越界还原（评审关注点 4"不会有两个 turn 同时写同一工作区"）。T7 的文件 PUT/回滚用 `TurnRunner.is_project_busy` 判断 409。
- 2026-09-27 — T6：跨轮的前言状态全部从持久化数据推出，重启后仍然有效：上一轮被还原的路径写成上一轮的 `notice` 事件（`payload.kind="guard_restored"`）；回滚通知 = 上一轮结束（`turns.updated_at`）之后出现的 `reason=rollback` 快照，回滚目标取它之前清单完全相同的最近一份快照（回滚原样写回目标清单），diff 相对上一轮的 `end_snapshot`；不新增表字段。
- 2026-09-27 — T6（审查后修正，替换本条最初的版本——最初只取本轮 `user_edit` 快照相对前一份快照的 diff，被定稿快照或其他阶段 turn 吸收的修改会丢失）："用户手动修改"= 本会话上一轮结束（`turns.updated_at`）之后、到本轮开始快照为止，项目里所有 `reason=user_edit` 快照（本轮开始、其他阶段 turn 开始、定稿时创建）各自相对前一份快照的 diff，按路径合并（基准取最早一次改动前、结果取最后一次）；新会话只看本轮自己的 `user_edit` 快照（交接摘要另外列出产物）。用"上一轮结束时间"而不是"上一轮 end_snapshot 在列表中的位置"做起点——end_snapshot 可能因清单去重指向更早的快照。
- 2026-09-27 — T6：落库的工具结果文本、工具参数中的字符串超过 8000 字符（`runner.TOOL_RESULT_MAX_CHARS`）时截断，`tool_result.payload.truncated` 标记是否截断；工具结果里的图片只落库 `media_type`，不存 base64 — 避免 `turn_events` 被大文件内容和图片撑大；完整内容仍在 SDK 会话存储里（设计 §4.1 两者独立）。
- 2026-09-27 — T6：持久事件的 payload 里带 `turn_id`（和表的 `turn_id` 列重复），落库和发布到总线的 payload 完全一致 — T8 回放与实时推送使用同一种格式，前端可以按 turn 分组。
- 2026-09-27 — T6：预算——`ToolCall` 计为一步，`Usage.cost_usd` 累加；超出 `model_profile.max_steps_per_turn`/`max_cost_per_turn` 时写一条 `notice`（`kind="budget_exceeded"`），置位取消令牌，最终状态 `budget_exceeded`（审查后修正：优先于一切——包括宽限期后强制 `task.cancel()` 导致的 `cancelled`、停止过程中运行时抛出的异常）；步数语义：上限为 N 时，第 N+1 次工具调用仍会落库，随后本轮停止（运行时可能已经执行了这次调用，事件如实记录）；`Budget` 同时传给运行时，运行时可以原生限制。`Usage` 事件上有可选属性 `auth == "login"` 时（T9 添加），成本只记录不限制，步数照常限制。
- 2026-09-27 — T6：取消——置位取消令牌，运行时 10 秒（`cancel_grace_seconds`）内没结束就 `task.cancel()`；task 被取消（`CancelledError`）也走同一个收尾流程，状态 `cancelled`。排队中的 turn 取消时直接标记 `cancelled`，不做快照（从未改动工作区）。
- 2026-09-27 — T6：`recover_on_startup` 把 `running` 和 `queued` 的 turn 都改为 `interrupted`（会话同样），`running` 的先做一份 `partial` 快照再改状态 — 排队信息只在内存里，`queued` 不处理会让会话永远"忙"；快照遵循"先快照后改状态"（§7）。恢复时不做越界检查（工具写入记录已随进程丢失，做了反而会把工具托管文件还原掉）。
- 2026-09-27 — T6：轮末越界检查之后重新物化一次 `upstream/`，agent 对只读副本的改动当场清除（R5），而不是等下一轮开始 — 画布上立即看到正确内容。（审查后补充）重新物化之前用新增的 `workspace.upstream_drift` 对比 `upstream/` 实际内容与本轮物化的内容，把不同的路径（`upstream/...`，含符号链接）并入被还原列表，写进 `guard_restored` notice，下一轮前言告知 agent（评审关注点 1）。
- 2026-09-27 — T6：`record_tool_write(relpath, sha)` 的实现读取磁盘上该文件的实际内容存入 blob 库，以实际内容的哈希为准（忽略传入的 sha）— `guard` 恢复工具版本时要求 blob 已存在；读取经新增的 `workspace.files.read_bytes`（规则 6）。
- 2026-09-27 — T6：`stage_flow.finalize` 先调用 `create_snapshot`（内容未变时返回最近一份）再写 `finalized_snapshot_id`，保证用户未快照的修改也进入定稿版本；下游 `locked` → `active` 并记录 `based_on_snapshot_id`，其他状态且 `based_on` 与新定稿不同 → `stale`；`reopen` 只允许从 `finalized` 出发；下游只有**成功**（`done`）的一轮结束后才更新 `based_on` 并从 `stale` 回到 `active`（失败的一轮可能没处理上游变更）。（审查后修正）`based_on` 记录的是**本轮开始时**物化到 `upstream/` 的上游定稿 id（`stage_flow.upstream_snapshot_ids`），不是轮末的最新定稿；轮中上游又定稿时下游保持 `stale`。M1 每个阶段最多一个上游，多上游时取上游顺序中第一个已定稿的。
- 2026-09-27 — T6：补充的仓储函数：`repo/sessions.py`（`create_session` 同时取消同阶段其他会话的活动状态、`get_session`）、`repo/turns.py`（turn 生命周期与事件）、`repo/stages.py`（阶段行读写，供 T7 建项目使用）、`profiles.get_model_profile_by_id`（会话存的是 id）。
- 2026-09-27 — T6（审查后新增）：收尾健壮性——写 turn 最终状态（`finish_turn`，含排队取消分支）失败时重试一次再记日志；运行时事件流在 `finally` 里 `aclose()`，runner 内部出错时也先关闭生成器（真实 SDK 的子进程）再做越界检查和快照；`recover_on_startup` 逐个 turn 兜底，一个失败不影响其他；`repo.turns.previous_turn` 跳过没有 `start_snapshot_id` 的 turn（排队中就被取消的），避免丢失更早一轮的还原路径、回滚基准和交接判断。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 2026-09-26 — 已确认 shadcn-vue 的 registry 列表中包含 `@ai-elements`，地址 `https://registry.ai-elements-vue.com/{name}.json`（来源：shadcn-vue 仓库 `apps/v4/public/r/registries.json`）；T11 时补进 frontend-stack.md。
- 2026-09-26 — 写计划时 PyPI 上的最新版本：`claude-agent-sdk 0.2.160`、`openai-agents 0.22.3`；以安装时锁定的版本为准。
- 2026-09-27 — T2 开始时工作区里已有一份未提交的 `db` 模块（`engine.py`/`models.py`/migrations/`tests/db/` 下 `test_engine.py`、`test_migrate.py`、`test_repo_profiles.py`、`test_repo_projects.py`），`pyproject.toml` 也已加上 `sqlalchemy`/`alembic` 依赖，但 `repo/` 目录本身不存在，`test_repo_*.py` 处于 RED（`ModuleNotFoundError`）——沿用这份已有实现（引擎、ORM 模型、迁移、测试用例均符合本任务要求，engine/migrate 相关测试本就是绿的），只补齐缺失的 `repo/projects.py`、`repo/profiles.py` 让 RED 转 GREEN，未重写已有代码。
- 2026-09-27 — T6：`runner.py` 实现完约 480 行（审查修复后约 516 行，含较长的中文 docstring），超出计划预期的 ~400 行；按控制者指示没有自行拆分，在报告中提出（可选的拆分：把 `_finish` 收尾与事件处理移到单独模块）。

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 无
