# M5：完善（设置页、风格库、会话内换模型、回退建议、旧风格导入）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 待验收 |
| 里程碑 | M5 |
| 设计依据 | [架构设计 §3.1（`model_profiles`/`style_presets`/`settings`）、§5.4、§5.5、§6.2、§10](../../design/2026-09-26-architecture.md) |
| 分支 | `m5-polish` |
| 批准记录 | 2026-09-30：负责人批准计划；确认旧项目 Postgres 已启动（T4 可直接做真实导出）；确认 TTS 真实试听产生的费用可以接受。执行方式：当前会话内联执行（沿用 M3/M4 做法，负责人批准时未另行指定）。起草前的输入（2026-09-30）：旧风格数据「你启动 Docker，我只读导出成 JSON」；风格映射问「能否做成 skill」（结论见 D1）；设置页范围全选，并新增「对话中可切换同一供应商的其他模型」和「TTS 试听（页面标注可能产生费用）」两项 |

## 目标

用户在设置页里管理模型配置（增改删、单价、预算）、各阶段默认模型、联网模式、TTS 音色与语速（可试听）和风格库；创建项目时选一套风格，项目里的叙事、动画、选题 agent 按需读取这套风格；对话进行中可以把模型换成同一供应商的另一个；下游 agent 提出的回退建议在对话流里是可处理的卡片，阶段导航上有角标，点「去处理」跳到上游阶段并预填内容。旧项目 dev DB 里的风格组件一次性导入成风格库的初始内容。

## 范围

**包含：**

- **风格库**：`style_presets` 加列（迁移 0004）、仓储、REST、校验；风格以 **skill 形态的目录**存放和落盘（D1）；创建项目时选风格（`style_preset_id`），没有任何预设时回退占位；默认风格；三个阶段提示词改为「按需读取 `style/` 下的文件」。
- **旧风格导入**：只读导出脚本（经 `docker compose exec` 对旧 Postgres 做 SELECT，不改旧项目任何文件）+ 新仓库内的导入转换（读导出的 JSON，不 import 旧代码，不新增依赖）。
- **`settings` 表的读写**与 `/api/settings`：各阶段默认模型、联网模式覆盖、新项目默认音色/语速、默认风格。`TurnRunner` 读「有效联网模式」（界面覆盖优先，未设置回落环境变量）。
- **模型配置增改删**（key 值仍只放 `backend/.env`，界面只改 `api_key_env` 的名字并显示是否已配置）、预算字段可编辑。
- **会话内换模型**：`PATCH /api/sessions/{id}`，只允许换成同 `runtime` 且同 `provider` 的配置；下一轮起生效；时间线出一条 `notice`；每轮 `usage` 记录实际用的模型。
- **TTS**：可用音色列表、试听（真实合成，带磁盘缓存避免重复计费）、项目级音色/语速修改（`PATCH /api/projects/{id}/settings`）。配音是否过期沿用 TD-36 的比较逻辑。
- **回退建议完整体验**：`suggestion` 事件落库并上 SSE；按项目/状态查询与 `apply`/`dismiss` 接口；`to_stage` 校验为直接上游；对话流卡片、阶段导航角标、「去处理」跳转并预填。
- 前端 `features/settings/`（模型配置 / 风格库 / 语音 / 通用四个子页，路由 `/settings/*`）。
- 文档：ADR 0011（风格 = skill 形态目录）、ADR 0012（会话内同供应商换模型）、ARCHITECTURE、QUALITY、tech-debt（处理 TD-39 的界面提示部分）、references、runbooks、glossary。

**不包含：**

- 用 SDK 的 skill 加载机制（Claude `ClaudeAgentOptions.skills`、OpenAI `ShellTool` 的 `skills`）。只借用 skill 的目录形态，理由见 D1。以后若要接 Claude 原生 skill，是一个独立的小改动。
- 给**已创建**的项目换风格（创建时复制，之后是项目自己的文件；要改就在项目里编辑 `style/`）。
- 跨供应商或跨运行时换模型；换模型时迁移对话历史。
- API key 值的界面录入与存储。
- 画幅、目标时长、渲染引擎等其他项目设置（设计 §3.1 提到，本里程碑没有需求）。
- 用 `OPENAI_API_KEY` 验证 OpenAI 托管搜索经 OpenRouter 是否可用（TD-39 剩余部分，会产生费用，仍需事先同意）；设置页只在联网模式旁标注「未验证」。
- 风格库的导入/导出界面（导入只有命令行）；风格的版本历史。
- 在界面上编辑 `STUDIO_*` 以外的环境配置（端口、数据目录等）。

## 验收标准

- [x] AC1：`settings` 仓储与 `/api/settings`：读取带默认值；写入校验（阶段名、模型配置存在且 key 已配置、联网模式只接受 `tools`/`native`、语速范围、音色在可用列表内、默认风格存在）；非法值 422，不落库；「联网模式」清除后回落环境变量；`TurnRunner` 下一轮生效且两种运行时行为一致（验证：`pytest backend/tests/db/test_settings_repo.py backend/tests/api/test_settings.py backend/tests/agent/test_web_mode.py`）
- [x] AC2：风格库后端：迁移 0004 在旧库上升级成功；预设的创建/编辑/删除/复制；校验（`STYLE.md` 必须有 `name`/`description` frontmatter；文件名不允许 `..`、绝对路径、重复；引用的文件必须存在）；`render_style_files` 把预设渲染成 `style/` 下的文件映射（验证：`pytest backend/tests/db/test_style_presets_repo.py backend/tests/workspace/test_style_files.py backend/tests/api/test_styles.py`）
- [x] AC3：创建项目选风格：`POST /api/projects` 带 `style_preset_id` 时 `style/` 目录按预设落盘且进入 `init` 快照，`project.settings` 记录风格 id 和名称；不带时用默认风格；库里没有任何预设时回退占位 `STYLE.md` 且不报错；预设之后被改或删不影响已有项目；风格 id 不存在返回 4xx 且不留半成品项目（验证：`pytest backend/tests/api/test_projects.py`）
- [x] AC4：旧风格导入：导出脚本对旧 Postgres 只执行 SELECT；导入把每个 `style_template` 转成一条预设（三类文本 → `references/` 三个文件，金样本 → `exemplars/`，入口 `STYLE.md` 生成）；重复导入幂等（同名跳过并报告，`--overwrite` 才覆盖）；缺类别、空文本、组件 id 悬空时给出点名的报告而不是崩溃（验证：`pytest backend/tests/db/test_legacy_styles.py`；真实导出证据在 `data/evidence/m5-polish/`）
- [x] AC5：三个阶段提示词在有 `style/` 目录时按阶段说明该读哪些文件（narrative：蓝图 + 金样本；animation：配色 + 动画风格；topic：只读入口），没有 `references/` 的占位风格不受影响；用本机 Claude 登录带导入的风格各跑一轮叙事、动画，确认 agent 确实读了对应文件（验证：提示词关键词断言 + `make smoke SMOKE_ARGS="-k style_claude_login"`，`turn_events` 中能看到对 `style/references/*` 的读取）
- [x] AC6：模型配置 CRUD：新增/编辑/删除；内置配置（种子名）不能删除；被任何会话引用的配置不能删除（409）；`runtime` 只接受已注册且非 `fake` 的运行时；单价/预算校验（非负；空表示不限）；环境变量网关覆盖的字段在响应里标 `env_override`；响应永不含 key 值（验证：`pytest backend/tests/db/test_profiles_repo.py backend/tests/api/test_profiles.py`）
- [x] AC7：会话内换模型：`PATCH /api/sessions/{id}` 换成同 runtime 且同 provider 的配置成功，下一轮 `TurnContext.model_profile` 是新配置，`turns.usage` 记录实际模型，时间线有换模型提示；有 `queued`/`running` 的 turn 时 409；跨 runtime/provider、key 未配置、配置不存在分别给出明确的 400；换模型后 `sdk_ref`、`is_active` 不变（验证：`pytest backend/tests/agent/test_model_switch.py backend/tests/api/test_sessions.py`；真实验证：`make smoke SMOKE_ARGS="-k model_switch_claude_login"`：第一轮告诉 agent 一个事实，换模型后第二轮 agent 仍记得）
- [x] AC8：TTS：`GET /api/tts/voices` 返回 `doubao_2.0` 音色的别名和中文标签；`POST /api/tts/preview` 真实合成固定示例文本，同一（音色、语速）第二次命中磁盘缓存不发请求；缺 `VOLCENGINE_TTS_API_KEY`、供应商报错、语速越界、未知音色各自返回可读错误；`PATCH /api/projects/{id}/settings` 只接受 `voice`/`speech_rate`，改后叙事画布按 TD-36 显示「配音已过期」（验证：`pytest backend/tests/api/test_tts.py backend/tests/api/test_projects.py`；真实试听一次，证据在 `data/evidence/m5-polish/`）
- [x] AC9：回退建议后端：`suggest_upstream_change` 记录 `turn_id`、校验 `to_stage` 是调用方的直接上游（否则工具返回错误说明可选阶段）、内容去空白后非空且有长度上限；`suggestion` 事件落库并出现在 SSE（回放与实时）；`GET /api/projects/{id}/suggestions?status=`、`POST /api/suggestions/{id}/apply|dismiss`（只能从 `open` 转出，重复操作返回 409）（验证：`pytest backend/tests/stages/test_suggest_upstream_change.py backend/tests/api/test_suggestions.py backend/tests/agent/test_runner_suggestion.py`）
- [x] AC10：设置页前端：四个子页可达；模型配置列表/编辑/新增/删除，未配置 key 的有提示，环境变量覆盖的字段只读并说明；通用页设置各阶段默认模型、联网模式（OpenAI 路径旁标注托管搜索未验证）、新项目默认音色/语速；语音页列出音色、设置默认值、试听按钮旁写明「会调用 TTS，可能产生费用」；风格库页列表、新建/复制/删除、编辑入口与引用文件与金样本、设默认（验证：vitest 纯逻辑用例 + L4 走查，截图见「验证记录」）
- [x] AC11：工作台前端：创建项目对话框有风格选择器（预选默认风格）；会话头部可换同供应商的其他模型，运行中禁用；新建会话的模型预选取该阶段默认；项目设置对话框改音色/语速并试听；回退建议在对话流里显示卡片（去处理/忽略），上游阶段在导航上有待处理数量角标；点「去处理」跳到上游阶段并把内容预填进输入框，目标阶段已定稿时先确认并重新打开，发送后建议标为 `applied`（验证：vitest + L4 走查，含真实 Fake 运行时走完「动画提建议 → 去叙事处理 → 建议变已处理」）
- [ ] AC12：`make check` 全绿；收尾清单（SOP §7）全部完成

## 评审关注点

下面这些输入或状态，设计没有说，但使用者很可能遇到。每一条都在对应任务里有测试。

1. **在有 turn 排队/运行时换模型，或换到 key 没配的配置。** 期望：拒绝并说明原因，当前轮不受影响（T7）。
2. **库里一条风格预设都没有就创建项目**（全新库、还没导入）。期望：回退占位 `STYLE.md`，不报错，也不要求先去设置页（T3）。
3. **重复导入旧风格。** 期望：不产生重复预设；使用者在界面里改过的预设默认不被覆盖（T4）。
4. **连续点多次「试听」同一音色、同一语速。** 期望：只有第一次产生 TTS 调用，后面命中缓存；没配 key 时给出明确提示而不是 500（T8）。
5. **同一条回退建议被处理两次，或目标阶段是 `locked`/已定稿。** 期望：第二次 409；`locked` 阶段不提供「去处理」；已定稿先确认并重新打开（T9、T13）。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->
<!-- 依赖顺序：T1 → T2、T6、T7、T10；T2 → T3 → T11；T2 → T4 → T5；T6 → T7、T10；T8 → T12；T7 → T12；T9 → T13。T4 的真实导出需要负责人先启动旧项目的 Docker（T4 之前的任务不受影响）。 -->

### T1：`settings` 仓储与 `/api/settings`，`TurnRunner` 读有效联网模式（完成）

- **目标**：给 `settings` 表一个带类型和校验的读写层，供默认模型、联网模式、TTS 默认、默认风格共用。
- **涉及文件**：新建 `backend/src/studio/db/repo/settings.py`、`backend/src/studio/api/settings.py`；改 `api/schemas.py`、`main.py`（挂路由）、`agent/runner.py`（`_tools_and_web` 读有效联网模式）；测试 `backend/tests/db/test_settings_repo.py`、`backend/tests/api/test_settings.py`、`backend/tests/agent/test_web_mode.py`。**不需要新迁移**：`settings` 表在 0001 已建。
- **接口与要点**：
  - 键固定为：`stage_default_profile`（`{stage: profile_id}`，阶段含 `brainstorm`）、`web_mode`（`tools`/`native`，缺省表示跟随环境变量）、`tts_default`（`{voice, speech_rate}`）、`default_style_preset_id`。未知键拒绝。
  - `get_all_settings(engine) -> SettingsValue`（带默认值的只读值对象）；`update_settings(engine, patch) -> SettingsValue`（整体校验、同一事务写入，要么全成要么全不成）。引用其他表的校验（模型配置、风格预设是否存在）在 api 层做，仓储只校验形状，避免 `db.repo` 之间互相依赖。
  - `effective_web_mode(engine, env_default) -> Literal["tools","native"]`：界面覆盖优先；`TurnRunner` 每轮读一次，不缓存。
  - `GET /api/settings` 同时返回 `web_mode_source: "ui"|"env"`，前端据此显示「来自环境变量」。
- **测试**：默认值；各键的非法值；部分更新不影响其他键；联网模式清除后回落环境变量；`TurnRunner` 在同一进程内改了联网模式后下一轮的工具列表变化（`tools` ↔ `native`），原生联网仍受 `_native_web_supported` 约束。
- **完成标准**：上述测试通过；现有 `test_web_mode.py` 不改断言也通过。
- **验证命令**：`make check`

### T2：风格库后端——迁移 0004、仓储、skill 形态渲染、REST（完成）

- **目标**：风格以「入口 + 引用文件 + 金样本」存在 `style_presets`，能渲染成工作区 `style/` 下的文件，并有完整的增删改查接口（D1、D2）。
- **涉及文件**：新建迁移 `db/migrations/versions/0004_style_preset_files.py`（加 `description`、`references` 两列，均可空，旧行兼容）；改 `db/models.py`；新建 `db/repo/style_presets.py`、`workspace/style_files.py`、`api/styles.py`；改 `api/schemas.py`、`main.py`；测试 `backend/tests/db/test_style_presets_repo.py`、`backend/tests/workspace/test_style_files.py`、`backend/tests/api/test_styles.py`、迁移测试沿用现有写法。
- **接口与要点**：
  - 列含义：`content` = `STYLE.md` 入口全文；`references` = `[{name, text}]`（落盘到 `style/references/<name>`）；`exemplars` = `[{name, text}]`（落盘到 `style/exemplars/<name>`）；`category` 沿用字段，取值由使用者自由填（如「概念传记」），仅用于界面分组。
  - `render_style_files(preset) -> dict[str, str]`：返回 `{"style/STYLE.md": ..., "style/references/x.md": ..., "style/exemplars/y.json": ...}`，供 `workspace.files.init_workspace` 使用。纯函数，不读写磁盘。
  - `validate_style_preset(...) -> list[str]`（中文错误列表）：`STYLE.md` 有 frontmatter 且含非空 `name`、`description`；文件名仅允许 `[\w.-]+`（不含路径分隔符、`..`），同一目录内不重复；`STYLE.md` 里出现的 `references/`、`exemplars/` 相对引用必须存在；单文件大小上限。
  - 路由：`GET/POST /api/style-presets`、`GET/PATCH/DELETE /api/style-presets/{id}`、`POST /api/style-presets/{id}/duplicate`。列表只返回摘要（id、name、category、description、文件数、是否默认）。
  - 删除默认风格时，`default_style_preset_id` 回落为空（由 api 层处理，T1 的设置读写）。
  - 新增模块在 ARCHITECTURE 补一行；`workspace/style_files.py` 归 `workspace` 层，没有新的 import-linter 契约需求，`make check` 里的现有分层契约必须仍通过。
- **测试**：渲染结果的路径与内容；各条校验的正反例（含 `..`、绝对路径、缺 frontmatter、引用不存在文件、重名）；复制后独立；删除默认风格回落；旧库升级到 0004 后旧行可读。
- **完成标准**：AC2 通过。
- **验证命令**：`make check`

### T3：创建项目时选风格（完成）

- **目标**：项目的 `style/` 目录来自所选预设；没有预设时行为和现在一样。
- **涉及文件**：`api/projects.py`（`_init_workspace`、`create_project_endpoint`）、`api/schemas.py`（`ProjectCreate.style_preset_id`、`ProjectOut.settings` 里记录 `style_preset_id`/`style_name`）、`workspace/files.py`（如需支持多文件初始内容，检查 `init_workspace` 现有签名是否已够用）；测试 `backend/tests/api/test_projects.py`。
- **接口与要点**：
  - 取风格顺序：请求里的 `style_preset_id` → `settings.default_style_preset_id` → 占位 `STYLE.md`。请求里的 id 不存在返回 404 且不创建任何东西。
  - `style/` 的全部文件进 `init` 快照；写入范围不变（各阶段都只读 `style/`）。
  - 项目只记风格的 id 和名称用于显示，不记内容；内容就是工作区文件。
  - 并发和失败清理沿用现有 `_cleanup_failed_project`。
- **测试**：选了风格 → 文件齐全且在 `init` 快照里；默认风格兜底；一条预设都没有 → 占位；预设之后被编辑/删除，已有项目的 `style/` 不变；id 不存在 → 404 且没有残留项目和工作区；从想法卡片创建时同样支持（`idea_id` + `style_preset_id`）。
- **完成标准**：AC3 通过。
- **验证命令**：`make check`

### T4：旧风格数据导出与导入（完成）

- **目标**：把旧项目 dev DB 里的风格组件一次性变成新风格库的初始预设。
- **涉及文件**：新建 `scripts/export_legacy_styles.sh`（只读导出）、`backend/src/studio/db/legacy_styles.py`（转换与导入，`python -m studio.db.legacy_styles import <json> [--overwrite]`）、`Makefile`（`make import-legacy-styles FILE=...`）；测试 `backend/tests/db/test_legacy_styles.py`（用手写的小 fixture JSON，结构按旧表字段写）；更新 `docs/references/legacy-assets.md` 中「风格组件内容」「风格组件编写经验」两行的状态。
- **接口与要点**：
  - **红线核对**：导出脚本只通过 `docker compose -f ../ai-video/docker-compose.yml exec -T <postgres 服务> psql` 执行 `SELECT`（`style_templates`、`prompt_components` 两表，`to_json` 输出），不写旧项目任何文件，不 import 旧代码；容器名、库名、账号从旧项目的 `docker-compose.yml` 和环境文件**读取**，不复制进本仓库。输出到 `data/legacy-export/styles.json`（`data/` 不进 git）。
  - 转换规则（D2）：旧 `style_templates.style_config` 按四个类别（`narrative_style`、`color_scheme`、`animation_style`、`exemplar`）引用 `prompt_components` 的 id。每个模板 → 一条预设：`name`/`description` 取模板；`narrative_style` → `references/narrative-blueprint.md`，`color_scheme` → `references/color-scheme.md`，`animation_style` → `references/animation-style.md`，`exemplar` → `exemplars/exemplar-<n>`（内容是纯 JSON 则 `.json`，否则 `.md`）；入口 `STYLE.md` 由程序生成：frontmatter（`name`、`description`）、一段「这套风格是什么」（取模板描述）、文件索引及每个阶段应读哪些文件（与 T5 的提示词一致）。**不改写组件正文**，原样落盘。
  - 幂等：按 `name` 匹配，已存在默认跳过并在报告里列出；`--overwrite` 才覆盖。报告写明新增、跳过、覆盖、有问题的模板（缺类别、空文本、组件 id 悬空）。
  - 金样本与新叙事 schema 的差异：导入后对每个 `.json` 金样本尝试用 `stages.narrative.schema` 解析，不符合的在入口索引里标注「旧格式，仅供参考旁白语感与信息密度」，不报错。
  - 真实导出需要负责人先执行 `docker compose up -d`（旧项目目录），执行者在开始本任务时向负责人确认已启动；未启动时只做脚本和转换的单测部分，把真实导入排到 T4 收尾，不阻塞 T6 及之后的任务。
- **测试**：fixture 转换出预期的文件集；重复导入幂等；`--overwrite`；缺类别/空文本/悬空 id 的报告；纯 JSON 与非 JSON 金样本的扩展名；旧格式金样本的标注；转换出的预设通过 T2 的 `validate_style_preset`。
- **完成标准**：AC4 通过；真实导出的 JSON 和导入报告存进 `data/evidence/m5-polish/`；风格库里有导入的预设。
- **验证命令**：`make check`；真实导入：`make import-legacy-styles FILE=data/legacy-export/styles.json`

### T5：三个阶段提示词按需读取风格目录 + 真实冒烟（完成）

- **目标**：agent 在正确的时机读正确的风格文件，而不是每轮把整套风格塞进上下文或完全不读。
- **涉及文件**：`stages/narrative/prompt.md`、`stages/animation/prompt.md`、`stages/topic/prompt.md`；`backend/tests/stages/` 下对应的提示词关键词断言；`backend/tests/smoke/`（新增 `style_claude_login` 用例，沿用现有冒烟的写法）；`docs/runbooks/verification.md` 补用例说明。
- **接口与要点**：
  - 每个提示词把现在「`style/STYLE.md`：自己读取」改成分层说明：入口 `STYLE.md` **每轮开始先读**；叙事阶段在动笔改 `narrative.json` 之前读 `references/narrative-blueprint.md` 和 `exemplars/`；动画阶段在写镜头代码之前读 `references/color-scheme.md` 与 `references/animation-style.md`；选题阶段只读入口。没有这些文件时（占位风格或旧项目）提示词的措辞要允许跳过。
  - 弱模型（DeepSeek 等）可能跳过按需读取，所以提示词里用「先读这些文件再动手」的强指令，而不是「需要时可以读」。
  - 不改 `style/` 的只读权限；不新增工具。
  - 已有的动画提示词「对任何风格都成立」的经验保留；如果导入的动画风格和它有冲突的规则，记进「意外与发现」，不在这个任务里改导入内容。
- **测试**：提示词里包含各阶段应读文件的路径；冒烟：用导入的一套风格创建项目，narrative 一轮后 `turn_events` 里有对蓝图和金样本的读取，animation 一轮后有对配色与动画风格的读取，产物通过各自的校验工具。
- **完成标准**：AC5 通过；冒烟证据存进 `data/evidence/m5-polish/`。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k style_claude_login"`（本机登录，不产生 API 费用）

### T6：模型配置增改删（完成）

- **目标**：模型配置可以在界面上维护，而不是只靠种子和环境变量。
- **涉及文件**：`db/repo/profiles.py`（`create_profile`/`update_profile`/`delete_profile`、内置判断）、`api/profiles.py`、`api/schemas.py`（`ModelProfileIn`/`ModelProfilePatch`，`ModelProfileOut` 增加 `builtin`、`env_override: list[str]`、`api_key_env`）；测试 `backend/tests/db/test_profiles_repo.py`、`backend/tests/api/test_profiles.py`。
- **接口与要点**：
  - `builtin` = 名字在 `_SEED_PROFILES`（及启用时的 `fake`）里。内置配置可编辑但不可删除（否则下次启动种子会把它加回来，行为违反直觉）；`name` 不可改。
  - 环境变量网关覆盖（`_gateway_overrides`）的字段仍然优先：启动时非空的配置值会覆盖界面里改过的值。`env_override` 列出当前被环境变量决定的字段，前端据此把它们置为只读。这是刻意保留的既有行为，写进决策记录。
  - 校验：`runtime ∈ {claude, openai}` 且已注册（`runtime_factory.has`）；`provider` 非空；`model` 非空；单价、`max_cost_per_turn` 非负，`max_steps_per_turn` 为正整数，空表示不限；`base_url` 必须是 http(s) URL；`api_key_env` 必须像环境变量名（`[A-Z_][A-Z0-9_]*`）或空（空表示本机登录，仅 `runtime=claude` 合法）。
  - 删除前检查是否有会话引用（`sessions.model_profile_id`），有则 409 并返回引用数量；同时检查 `settings.stage_default_profile` 是否引用，引用时 409。
  - `max_cost_per_turn=0` 的现有语义（直接拒绝运行，TD-12）保持，界面对 0 给出警告（T10）。
  - 响应永远不含 key 值，只有 `key_configured`。
- **测试**：各校验的正反例；内置不可删、不可改名；被会话或阶段默认引用的不可删；`env_override` 的计算；编辑后 `get_model_profile_by_id` 立即可见，已有会话下一轮用新值。
- **完成标准**：AC6 通过。
- **验证命令**：`make check`

### T7：会话内换模型（完成）

- **目标**：一个会话可以在同供应商的模型之间切换，对话记忆保留（D3）。
- **涉及文件**：`api/sessions.py`（`PATCH /sessions/{id}`）、`db/repo/sessions.py`（更新 `model_profile_id`）、`agent/runner.py`（每轮本就重新读配置，补换模型提示与 `usage` 记录实际模型）、`agent/turn_finish.py`（`usage.model`）、`api/schemas.py`；测试 `backend/tests/agent/test_model_switch.py`、`backend/tests/api/test_sessions.py`；冒烟 `backend/tests/smoke/`（`model_switch_claude_login`）；新增 ADR `docs/decisions/0012-会话内同供应商换模型.md`。
- **接口与要点**：
  - 允许条件：目标配置存在、`runtime` 与当前相同、`provider` 与当前相同、`key_configured`；会话没有 `queued`/`running` 的 turn；`brainstorm` 的无项目会话同样可换。不满足各返回明确的 400/409。
  - 只改 `sessions.model_profile_id`，`sdk_ref`、`is_active`、历史不动。**Claude 侧 `resume` 换模型、以及 `claude-login` ↔ `claude-sonnet`（登录 ↔ API key）互换是否保持记忆，必须先用冒烟实测**；如果登录↔key 互换不行，把允许条件收紧到「同 `api_key_env`」并在 ADR 写明。OpenAI 路径的 `SQLiteSession` 与模型无关，只做 mock 测试。
  - 下一轮开始时，如果本轮配置与上一轮不同，向会话推一条 `notice`（「模型已从 A 换为 B」，落库、可回放）。`turns.usage` 增加 `model`、`profile_name`（无迁移，`usage` 是 JSON）。成本和预算按本轮实际配置计算。
  - 成本账本按 SDK 会话 id 记账（TD-11），换模型不新开 SDK 会话，账本不受影响；价格不同时本轮的 `cost_usd` 用新配置的单价（OpenAI 路径）或 SDK 报告值（Claude 路径）。
- **测试**：允许与各种拒绝；运行中 409；换模型后下一轮用的是新配置且 `usage` 有模型名；`notice` 出现一次且可回放；换来换去不丢 `sdk_ref`；预算上限按新配置。冒烟（本机登录）：第一轮告诉 agent 一个随机词，换成另一个 Claude 模型配置，第二轮问它，agent 答得出。
- **完成标准**：AC7 通过；ADR 0012 写明实测结论。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k model_switch_claude_login"`

### T8：TTS 音色列表、试听与项目语音设置（完成）

- **目标**：使用者能看到有哪些音色、试听、并给项目设置音色和语速。
- **涉及文件**：`engines/tts/voice_map.py`（补中文标签；新增 `list_voices(engine)`，标签来自 `docs/references/volcengine-tts.md` 记录或旧项目音色表，**先查证再写**）、新建 `api/tts.py`、改 `api/projects.py`（`PATCH /projects/{id}/settings`）、`api/schemas.py`；测试 `backend/tests/api/test_tts.py`、`backend/tests/api/test_projects.py`、`backend/tests/engines/tts/` 下音色列表用例。
- **接口与要点**：
  - `GET /api/tts/voices` → `[{alias, label, engine}]`，当前固定 `doubao_2.0`。
  - `POST /api/tts/preview {voice, speed}` → `audio/mpeg`。示例文本固定为一句中文（写在代码常量里，不接受调用方自定义，避免被当成免费合成接口）。结果缓存到 `data/tts-preview/<sha256(voice|speed|text|engine)>.mp3`（数据目录内，不在 uvicorn 监听范围）；命中缓存不调用供应商。同一键的并发请求合并为一次合成。
  - 语速范围以 `volcengine-tts.md` 已验证的范围为准（不在文档里的先实测并补进文档）；越界 422。缺 `VOLCENGINE_TTS_API_KEY` 返回 503 并指向 `backend/.env`，供应商报错返回 502 并带不含 key 的说明。
  - `PATCH /api/projects/{id}/settings` 只接受 `voice`、`speech_rate`，合并进 `projects.settings`，其他键拒绝；与 `synthesize_tts` 读取的 `settings["voice"]`、`settings["speech_rate"]` 对齐（核对现有键名）。阶段没有 turn 在跑时才允许改（项目级串行，沿用 `_require_not_busy`）。
  - 新项目默认音色/语速：创建项目时若请求未给，取 `settings.tts_default` 写进 `project.settings`（复制，不做活继承）。
- **测试**：音色列表；试听成功、缓存命中不再发请求（mock 引擎计数）、并发合并、缺 key、供应商失败、越界语速、未知音色；`PATCH` 只改允许的键、项目忙时 409、改后 `synthesize_tts` 读到新值；创建项目带默认。
- **完成标准**：AC8 通过；真实试听一次（会产生少量 TTS 费用，计划已说明）的音频文件和响应头存进 `data/evidence/m5-polish/`。
- **验证命令**：`make check`

### T9：回退建议后端（完成）

- **目标**：回退建议从「只写进表」变成有事件、有接口、有状态流转的完整后端。
- **涉及文件**：`stages/common/suggest_upstream_change.py`、`agent/tools.py`（`ToolContext` 增加 `turn_id`，若没有）、`agent/turn_events.py`（工具成功后发 `suggestion` 事件）、`api/sessions.py`（`WIRE_EVENT_TYPES` 增加 `suggestion`）、新建 `api/suggestions.py`、`db/repo/suggestions.py`（`apply`/`dismiss` 状态机、按项目统计待处理数）、`api/schemas.py`、`main.py`；`agent/bus.py` 文档注释里的事件类型说明同步；测试见 AC9。
- **接口与要点**：
  - 工具校验：`to_stage` 必须在调用方 `StageDefinition.upstream_stages()` 里（直接上游，D4）；否则返回错误，文本列出可选阶段；`content` 去空白后非空，长度上限 2000 字；写入 `turn_id=ctx.turn_id`。
  - `suggestion` 事件负载：`{suggestion_id, from_stage, to_stage, content}`，和 `turn_events` 其他持久事件一样落库、回放、走总线。
  - 状态机：`open → applied | dismissed`，其他转移 409；`apply` 可带 `session_id`/`turn_id` 之外不需要其他参数。
  - `GET /api/projects/{id}/suggestions?status=`，另有 `GET /api/projects/{id}/suggestions/summary` → `{to_stage: open 数量}`，供阶段导航角标。
- **测试**：`to_stage` 合法/非法（含下游、自身、不存在）；空内容/超长；事件落库并回放；状态机各转移；`summary` 计数；未知建议 404；已 `applied` 的再 `apply` 409。
- **完成标准**：AC9 通过。
- **验证命令**：`make check`

### T10：前端设置页——框架、通用、模型配置（完成）

- **目标**：设置页的四个子页骨架，以及「通用」和「模型配置」两页。
- **涉及文件**：改 `frontend/src/router.ts`（`/settings` 下四个子路由，`/settings` 重定向到模型配置）、`router.spec.ts`、`pages/SettingsPage.vue`（布局 + 子导航）；新建 `features/settings/`：`ModelProfilesPanel.vue`、`ModelProfileDialog.vue`、`GeneralPanel.vue`，纯逻辑 `profileForm.ts`（表单校验与后端一致）、`settingsView.ts`；改 `api/endpoints.ts`、`types/api.ts`、`composables/queries.ts`；对应 `.spec.ts`。
- **接口与要点**：
  - 模型配置页：列表显示名称、供应商、模型、运行时、key 状态、单价、预算；编辑/新增/删除（删除用确认对话框，409 时显示原因）；`env_override` 的字段只读并注明「由环境变量决定」；`max_cost_per_turn=0` 显示「会让每一轮都被拒绝」的警告。
  - 通用页：各阶段默认模型（含头脑风暴；只列 key 已配置的）、联网模式（`tools`/`native`，显示来源 `ui|env`，可清除回落环境变量；选 `native` 时说明无 URL 来源保护，OpenAI 路径旁标注托管搜索经 OpenRouter 未验证，TD-39）、新项目默认音色/语速（音色下拉来自 T8 接口，T12 前先用文本输入占位则在这里改成下拉——T8 先于 T10 完成时直接做下拉）。
  - 风格库、语音两个子页此时是带标题的占位，分别由 T11、T12 填充。
  - `features/*` 之间不互相 import；共用的下拉/表单块放 `components/`。
- **测试**：`profileForm.ts` 与后端同一组正反例；`settingsView.ts` 的来源文案与只读字段判断；路由表包含四个子路由。
- **完成标准**：AC10 中模型配置与通用部分；L4 走查截图。
- **验证命令**：`make check`；`cd frontend && pnpm exec vitest run`

### T11：前端风格库页与创建项目选风格（完成）

- **目标**：风格库的管理界面，以及创建项目时选风格。
- **涉及文件**：新建 `features/settings/StylePresetsPanel.vue`、`StylePresetEditor.vue`（左侧文件树：`STYLE.md`、`references/*`、`exemplars/*`，右侧 `components/CodeEditor.vue`）、`styleDraft.ts`（草稿状态、校验、与后端一致的文件名规则）；改 `features/ideas/CreateProjectDialog.vue`（风格下拉，预选默认）、`composables/queries.ts`、`api/endpoints.ts`、`types/api.ts`；`.spec.ts`。
- **接口与要点**：列表分组（按 `category`）、新建、复制、删除（确认）、设为默认；编辑器里增删引用文件和金样本；保存时后端校验错误按文件点名显示；`STYLE.md` 缺 frontmatter 时保存按钮旁直接提示。`CreateProjectDialog` 没有任何预设时隐藏选择器，并在提示里说明「将使用占位风格」。
- **测试**：`styleDraft.ts` 的文件名规则、frontmatter 检测、引用存在性检查；创建项目对话框的预选逻辑抽成纯函数（默认风格存在/不存在/已被删）。
- **完成标准**：AC10 风格库部分、AC11 创建项目部分；L4 走查：导入的预设能编辑、复制、设为默认，新项目的 `style/` 文件树里出现对应文件。
- **验证命令**：`make check`；`cd frontend && pnpm exec vitest run`

### T12：前端语音页、会话内换模型与项目设置（完成）

- **目标**：语音设置与试听；工作台里换模型；新建会话的模型预选；项目级音色/语速。
- **涉及文件**：新建 `features/settings/VoicePanel.vue`；新建 `components/session/ModelSwitcher.vue`（会话头部下拉，只列同 runtime、同 provider、key 已配置的配置，运行中禁用）、纯逻辑 `modelSwitch.ts`；改 `components/session/SessionPicker.vue`（预选取阶段默认模型，而不是「第一个已配置的」）、`components/session/SessionTimelineItem.vue`（`notice` 已能显示则只确认文案）；新建 `features/workbench/ProjectSettingsDialog.vue`（音色、语速、试听）并接进 `ProjectWorkbenchPage.vue`；`composables/queries.ts`、`api/endpoints.ts`、`types/api.ts`；`.spec.ts`。
- **接口与要点**：
  - 试听按钮旁固定文案「试听会调用 TTS，可能产生费用」；请求中禁用按钮，失败显示后端的中文原因；音频用 `<audio>` 播放 `POST` 返回的 blob。
  - `ModelSwitcher` 的可选项计算放进 `modelSwitch.ts`（纯函数：当前会话的配置 + 全部配置 → 可选列表及被禁用原因）。
  - 改项目音色/语速后，叙事画布的「配音已过期」提示（TD-36）应自动出现；项目设置对话框在项目忙时只读。
- **测试**：`modelSwitch.ts` 各种组合（跨 runtime、跨 provider、key 未配置、当前项）；阶段默认模型预选的纯函数（默认存在/已被删/key 未配置）。
- **完成标准**：AC10 语音部分、AC11 换模型与项目设置部分；L4 走查含一次真实试听和一次真实换模型（Fake 运行时换模型、Claude 登录换模型各一次）。
- **验证命令**：`make check`；`cd frontend && pnpm exec vitest run`

### T13：前端回退建议（完成）

- **目标**：回退建议在界面上可见、可处理。
- **涉及文件**：新建 `components/session/SuggestionCard.vue`、纯逻辑 `suggestionFlow.ts`；改 `components/session/SessionTimelineItem.vue`（渲染 `suggestion` 事件）、`composables/useSessionStream.ts`（处理 `suggestion` 事件、失效建议查询）、`types/events.ts`、`features/workbench/StageNav.vue`（角标）、`pages/ProjectWorkbenchPage.vue`（读路由 query 里的 `suggestion`，预填输入框）、`components/session/SessionPanel.vue`（接受预填文本）；`composables/queries.ts`、`api/endpoints.ts`；`.spec.ts`。
- **接口与要点**：
  - 卡片显示来源阶段、目标阶段、内容，按钮「去处理」「忽略」；已处理/已忽略的卡片灰显且无按钮。
  - 「去处理」：目标阶段 `locked` 不提供；已定稿先弹确认并复用 `useReopenStageMutation`；然后跳转 `/projects/:id/<to_stage>?suggestion=<id>`，输入框预填建议内容，使用者可改；发送成功（202）后再调 `apply`，失败则建议仍是 `open`。
  - `StageNav` 角标显示 `summary` 里该阶段的待处理数量，使用 `stageStatus.ts` 的既有风格约定。
  - 「忽略」直接调 `dismiss`。
- **测试**：`suggestionFlow.ts`（目标阶段状态 → 可用动作、预填文本、重复点击的处理）；`useSessionStream` 对 `suggestion` 事件的归并（回放与实时去重）。
- **完成标准**：AC11 回退建议部分；L4 走查：Fake 运行时脚本让动画阶段提一条建议，卡片出现、叙事阶段角标 +1、点「去处理」后自动跳转并预填、发送后卡片变「已处理」、角标消失。
- **验证命令**：`make check`；`cd frontend && pnpm exec vitest run`

### T14：文档收尾与整体走查（完成）

- **目标**：SOP §7 的收尾清单，以及把所有真实验证汇总到一处。
- **涉及文件**：`docs/decisions/0011-风格库采用skill形态目录.md`（D1：为什么不用 SDK skill 机制、目录结构、`style_presets` 加列；偏离设计 §3.2 的 `style/` 内容）、`docs/decisions/0012-...`（T7 已写，这里补实测结论）、`docs/ARCHITECTURE.md`（`workspace/style_files`、`db/legacy_styles`、`api/{settings,styles,tts,suggestions}`、`features/settings/`、`components/session/ModelSwitcher|SuggestionCard`，去掉「（M5）」标注）、`docs/quality/QUALITY.md`、`docs/quality/tech-debt.md`（TD-39 界面提示部分移到已处理；登记本计划新发现的债）、`docs/references/`（Claude `skills` 选项与 OpenAI `ShellTool` skills 的核实结论、`resume` 换模型的实测、TTS 语速范围，注明日期和来源）、`docs/references/legacy-assets.md`、`docs/glossary.md`（风格预设、skill 形态目录、金样本、会话内换模型、回退建议卡片）、`docs/runbooks/dev-setup.md` 与 `verification.md`（导出/导入命令、新冒烟用例）、`AGENTS.md`（仅当命令有变）。
- **完成标准**：SOP §7 清单全部勾选；「整理」一项要做：检查有没有可以改成机器检查的文字约定（例如「`style/` 文件名规则」前后端各写一份，评估是否抽成共享的测试夹具）；从技术债里挑一两项顺手处理或排进下一个计划。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-09-30 — 计划起草；负责人批准；建分支 `m5-polish` 与 worktree `.claude/worktrees/m5-polish`。
- 2026-09-30 — T1 完成：`db/repo/settings.py`（补丁语义、整体校验、`effective_web_mode`）、`api/settings.py`（`GET/PATCH /api/settings`，引用检查：模型配置存在/运行时已启用/key 已配置，音色在可用列表内）、`TurnRunner._tools_and_web` 每轮读有效联网模式；`engines/tts/voice_map.py` 公开 `DEFAULT_ENGINE/VOICE/SPEED` 与 `voice_aliases()`，`synthesize_tts` 改用它们；`api/profiles.key_configured` 改为公开函数。`make check` 全绿。
- 2026-09-30 — T2 完成：迁移 0004（`description`、`reference_files` 两列）、`db/repo/style_presets.py`（校验 + CRUD + 复制）、`workspace/style_files.py::render_style_files`、`api/styles.py`（`/api/style-presets*`）；`PATCH /api/settings` 补上默认风格存在性检查，删除默认风格时清掉设置（T1 留下的一项）。`make check` 全绿（1117 个后端测试）。
- 2026-09-30 — T3 完成：`POST /api/projects` 支持 `style_preset_id`（请求指定 → 默认风格 → 占位；id 不存在 404 且无残留），风格文件经 `render_style_files` 写入 `style/` 并进 `init` 快照，`project.settings` 记 `style_preset_id`/`style_name`（客户端传同名键会被丢掉，防伪造）；预设之后被改/删不影响已有项目。`make check` 全绿（1126 个后端测试）。
- 2026-09-30 — T4 完成：`scripts/export_legacy_styles.sh`（`make export-legacy-styles`，只读会话，从旧 compose 文件读库名/用户名）、`db/legacy_styles.py`（`make import-legacy-styles`，幂等、`--overwrite`、报告）；真实导出 9 个模板、34 个组件，导入 9 套预设到 worktree 的 `data/studio.db`，再导入全部跳过、`--overwrite` 覆盖 9 套均验证过，证据 `data/evidence/m5-polish/t4-legacy-import.md`。`make check` 全绿（1160 个后端测试）。
- 2026-09-30 — T5 完成：narrative/animation/topic 三个提示词改为分层读取（入口每轮先读；叙事动笔前读蓝图和金样本；动画写代码前读配色和动画风格；选题只读入口；文件不存在则跳过；旧字段名/与基础规则冲突时以提示词为准），对应关键词断言；冒烟 `test_style_claude_login`（本机登录，111 秒）真实通过：叙事一轮先读入口和简报、再读蓝图与金样本、之后才 Write，产物通过 `validate_narrative`（2 个镜头，旧字段名没有带偏）；动画一轮先读入口、再读配色与动画风格、之后才 Write，`validate_scenes` 通过；证据 `data/evidence/m5-polish/smoke/20260930T131101Z-style-claude-login.json`。
- 2026-09-30 — T6 完成：`db/repo/profiles.py`（校验、`create/update/delete_model_profile`、内置保护、被会话或阶段默认引用时不能删、`env_override_fields`）、`api/profiles.py`（`POST/PATCH/DELETE /api/model-profiles`，列表增加 `api_key_env`/`base_url`（打码）/`builtin`/`env_override`）。`make check` 全绿（1237 个后端测试）。
- 2026-09-30 — T7 完成：`PATCH /api/sessions/{id}`（同 runtime、同 provider、key 已配置、Claude 只在同一种认证方式内；有排队/运行中的 turn 返回 409）、仓储 `set_session_model_if_idle`（同一事务里检查再更新）、每轮 `usage` 记录 `model`/`profile_name`、换了之后第一轮的 `model_switched` `notice`（`turn_events.note_model_switch`，无项目会话同样支持）。真实冒烟 `model_switch_claude_login` 通过：同一 SDK 会话 Sonnet → Haiku，`sdk_ref` 不变，第二轮答出第一轮的背景；ADR 0012、claude-agent-sdk.md、TD-41 已写。`make check` 全绿（1264 个后端测试）。
- 2026-09-30 — T8 完成：`engines/tts/voice_map.py`（`VoiceInfo`/`list_voices`，中文名和性别取自旧库 `tts_voices` 表的只读查证）、`api/tts.py`（`GET /api/tts/voices`、`POST /api/tts/preview`：固定示例文本、磁盘缓存 `data/tts-preview/`、并发合并、失败不缓存、缺 key 503/供应商错误 502/越界或未知音色 422）、`PATCH /api/projects/{id}/settings`（只放行 `voice`/`speech_rate`，项目忙 409，`null` 清除）、`update_project_settings` 仓储、创建项目时复制 `settings.tts_default`。真实试听 `tts_preview_real` 通过：5 段合成，语速 0.5–2.0 两端供应商都接受且真实生效（zizi 0.5/1.0/2.0 → 11.69/6.43/2.95 秒），缓存命中；结论写进 `references/volcengine-tts.md`，证据 `data/evidence/m5-polish/smoke/`。`make check` 全绿（1307 个后端测试）。
- 2026-09-30 — T9 完成：`suggest_upstream_change` 只允许向直接上游提（`ToolContext.upstream_stages`，由 runner 从 `StageDefinition.upstream_stages()` 传入）、内容去空白后非空且 ≤ 2000 字、记录 `turn_id`（`ToolContext`/`TurnContext` 新增 `turn_id`、`upstream_stages`）；`turn_events` 在工具成功后按 `turn_id` 查回新建的建议，各发一条持久的 `suggestion` 事件（三个运行时一致，`WIRE_EVENT_TYPES` 增加它）；`db/repo/suggestions.py` 增加 `resolve_suggestion`（`open → applied | dismissed`，重复 `SuggestionStateError`）、`list_turn_suggestions`、`count_open_by_target_stage`；`api/suggestions.py`：`GET /api/projects/{id}/suggestions?status=`、`.../suggestions/summary`、`POST /api/suggestions/{id}/apply|dismiss`。`make check` 全绿（1357 个后端测试）。后端部分（T1–T9）到此完成，接下来是前端（T10–T13）。
- 2026-09-30 — T10 完成：`/settings` 改为外壳 + 四个子路由（`/settings/{models,styles,voice,general}`，`/settings` 重定向到 models）；`features/settings/`：`profileForm.ts`（校验与后端同一组规则，表单 ↔ 请求体，补丁只含改过且非环境变量决定的字段）、`settingsView.ts`（默认模型可选项、联网模式来源文案与风险提示、锁定字段、key 状态）、`ModelProfilesPanel`/`ModelProfileDialog`（增改删）、`GeneralPanel`（各阶段默认模型、联网模式）；`api/http.ts::errorMessage`（兼容 pydantic 的 422 列表）；types/endpoints/queries 同步。vitest 从 220 增到 282。L4 走查（内置浏览器 + worktree 的 dev server，Fake 运行时）通过：模型配置列表（内置徽章、密钥状态、环境变量决定的字段提示）、编辑 `gpt` 的步数上限 12 并落库、环境变量锁定的字段禁用并说明、空表单三条校验错误点名、新增 `ui-test` 后删除、内置配置的删除按钮禁用、通用页联网模式切到原生后出现风险提示与「清除界面设置」按钮、默认模型只列密钥已配置的且落库；截图 `data/evidence/m5-polish/l4/t10-*.jpg`。`make check` 全绿。
- 2026-09-30 — T11 完成：风格库页（`StylePresetsPanel` 按分类分组的列表 + `StylePresetEditor` 文件树/CodeMirror、新建/保存/放弃/复制/设默认/删除，未保存修改切换时确认）、`styleDraft.ts`（校验与后端 `validate_style_preset` 一致、文件增删改、补丁只含改过的字段）、创建项目选风格：共用 `composables/styleChoice.ts` + `components/StyleSelect.vue`，接进项目页新建对话框和选题池的「创建项目」对话框（预选默认风格，风格库为空时提示占位）；类型/接口/hooks 同步；`App.vue` 给 `SidebarInset` 加 `min-w-0`（宽内容不再把整页撑出横向滚动条，顺带修了外壳的通用问题）。vitest 增到 327。L4 走查（内置浏览器）通过：导入的 9 套旧风格按「旧项目导入」分组显示、编辑器显示入口与 3 个引用 + 1 个金样本、空名称/不合法文件名当场报错、新建并添加文件后落库、设为默认后新建项目对话框预选它并显示描述、复制出「（副本）」并自动选中、删除；在项目页选「概念传记·纸上溯源」创建项目，工作区 `style/` 下有入口、3 个引用、1 个金样本 5 个文件；截图 `data/evidence/m5-polish/l4/t11-*.jpg`。`make check` 全绿。
- 2026-09-30 — T12 完成：语音页（`VoicePanel`：音色列表、新项目默认音色/语速、试听旁固定写明会产生费用）、共用的试听（`composables/useVoicePreview.ts` + `components/VoicePreviewButton.vue`，缺 key/供应商出错时在按钮下显示后端的中文原因）、项目设置对话框（`features/workbench/ProjectSettingsDialog.vue`，入口在阶段导航条，项目忙时只读）、会话内换模型（`components/session/ModelSwitcher.vue` + `modelChoice.ts`：规则与后端一致，不可选的选项灰掉并写原因）、`SessionPicker` 预选该阶段的默认模型、`noticeText.ts`（`model_switched` 直接显示那句话）；类型/接口/hooks 同步。vitest 增到 360。L4 走查（内置浏览器 + 真实后端）通过：语音页 5 个音色；缺 key 时点试听显示「环境变量 VOLCENGINE_TTS_API_KEY 未设置，请在 backend/.env 中配置」；配好 key 后真实试听 200、音频缓存落盘、界面无报错；项目设置改成 xiaohe/1.3 并落库；把选题阶段默认模型设为 claude-login 后新建会话预选它；换模型下拉里只有 claude-login 和 Haiku 可选，其余灰掉并写明「运行时不同」「认证方式不同」；用本机 Claude 登录真实跑两轮：第一轮 Sonnet 说背景，换成 Haiku，第二轮时间线出现「模型已从 claude-login 换为 claude-login-haiku（claude-haiku-4-5-20251001）」，Haiku 答出「退休的数学老师」；截图 `data/evidence/m5-polish/l4/t12-*.jpg`。`make check` 全绿。
- 2026-09-30 — T13 完成：`suggestion` 事件进时间线（`useSessionStream` 新增 `SuggestionItem`，同时让所有建议查询失效）、`SuggestionCard`（来源阶段 → 目标阶段、内容、状态徽标、「去处理」「忽略」，目标阶段已定稿先确认并重新打开，未开放时禁用并说明）、`suggestionFlow.ts`（动作、预填、跳转、角标的纯逻辑）、`PromptPrefill`（往 `PromptInput` 预填）、`SessionPanel` 的 `prefill`/`sent`、`StageNav` 阶段按钮角标、`ProjectWorkbenchPage` 读 `?suggestion=` 预填并在发送成功后标为已处理、类型/接口/hooks 同步。vitest 增到 374。L4 走查（内置浏览器；用仓储函数在开发库里造「叙事已定稿、动画进行中」的项目和一条建议，走的是与 `suggest_upstream_change` + TurnRunner 相同的落库路径）通过：动画会话里出现「回退建议：动画 → 叙事 待处理」卡片，叙事阶段按钮有角标 1；点「去处理」弹确认「先重新打开叙事阶段？」，确认后叙事阶段变 `active`、跳到 `narrative?suggestion=…`、输入框预填建议内容；新建会话并发送后建议变 `applied`、角标消失、`?suggestion=` 被清掉、输入框清空；回动画阶段卡片灰显「已处理」且没有按钮；截图 `data/evidence/m5-polish/l4/t13-*.jpg`。`make check` 全绿。前端 T10–T13 全部完成。
- 2026-09-30 — T14 完成（文档与最终自验证部分）：ADR 0011、ARCHITECTURE（新模块、去掉「（M5）」标注）、QUALITY、tech-debt（TD-42 新登记；TD-39 的设置页提示部分进「已处理」）、glossary、runbooks（dev-setup：设置页/风格库导入/试听所需环境；verification：worktree 里做 L4 的方法、三个新冒烟用例）、AGENTS.md 命令表；新增冒烟 `suggestion_claude_login`（Claude 侧工具名前缀去掉后 `suggestion` 事件仍正确发出）；四个 M5 冒烟（`style_claude_login`、`model_switch_claude_login`、`tts_preview_real`、`suggestion_claude_login`）在最终代码上再跑一遍全部通过（145 秒）。走查用的后台 dev server 已停。
- 2026-09-30 — 独立评审（`code-review` high）处理完毕：9 条中修 5 条（另有一条修了未在浏览器复验），跳过 3 条（详见「验证记录」），登记 TD-43；`make check` 全绿（后端 1367、前端 376）。状态改为待验收。

## 下一步

- **等负责人验收**（SOP §3 第 6 步）。验收通过后：
  1. 计划移到 `docs/plans/completed/m5-polish.md`（状态改「已完成」），ADR 0011/0012 里指向 `../plans/active/m5-polish.md` 的链接改为 `completed/`；勾选 SOP §7 收尾清单（AC12）。
  2. 把 `m5-polish` 用 `--no-ff` 合并到 `main`，在 main 上再跑一次 `make check`。
  3. 在主检出导入旧风格：把 worktree 的 `data/legacy-export/styles.json` 复制到主检出的 `data/legacy-export/`（或重新 `make export-legacy-styles`），跑 `make import-legacy-styles`。
  4. 清理 worktree。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- **D1 风格 = skill 形态的目录，不用 SDK 的 skill 加载器**（2026-09-30，起草时）。负责人问「能否做成 skill」。核实已安装版本的 SDK 源码（`claude-agent-sdk 0.2.160`、`openai-agents 0.22.3`）：Claude 的 `ClaudeAgentOptions.skills` 靠文件系统发现 skill，需要打开设置来源，和现在 `setting_sources=[]` 的隔离冲突，且 skill 目录会落在工作区里被扫描进快照；OpenAI 的 skill 只挂在 `ShellTool` 的 `local`/`container` 环境上，而本项目在非官方 `base_url` 或非 macOS 上不提供 Shell，LiteLLM 接入的模型没有 skill。所以不能用它当统一机制。借用它的**目录形态**和渐进披露思想：`style/STYLE.md` 是入口（frontmatter `name`/`description`、风格概述、文件索引及各阶段该读什么），细节放 `style/references/*.md`，金样本放 `style/exemplars/*`；三个运行时都只用原生文件工具读取。好处：入口很短，叙事、动画、选题各读各的，金样本可以单独替换。代价：依赖提示词里的强指令让 agent 去读（T5 测）。影响范围超出本计划（改了 `style/` 的内容约定和 `style_presets` 的列），写 ADR 0011（T14）。
- **D2 旧风格的映射**（2026-09-30，起草时）。旧库每套风格由四类组件组成（`narrative_style` 叙事蓝图、`color_scheme`、`animation_style`、`exemplar`），由 `style_templates` 组合。新库一套风格是一条 `style_presets`。映射见 T4。正文不改写，原样导入；差异（旧金样本的 JSON 结构与新叙事 schema 不完全一致、旧蓝图里可能引用旧系统的输出格式）只标注、记录，不在导入时「修正」，避免无意改变已经调好的提示词内容。
- **D3 会话内换模型的边界**（2026-09-30，起草时）。设计 §1 写的是「运行时由所选模型决定，会话中途不切换」，本计划放宽为「同 runtime 且同 provider 内可切」（Claude 系列之间、OpenAI 官方配置之间等）。`TurnRunner` 本来每轮都按 `session.model_profile_id` 重读配置，所以实现很小；风险在 Claude SDK 的 `resume` 换模型、登录↔API key 互换是否保留记忆，先实测再定边界（T7）。写 ADR 0012。
- **D4 回退建议只允许向直接上游提**（2026-09-30，起草时）。`suggest_upstream_change` 目前 `to_stage` 是任意字符串。动画只能向叙事提，叙事只能向选题提。理由：直接上游的产物就是本阶段的输入，建议才有明确的处理对象；跨级建议可以让使用者自己去处理。
- **D5 默认值的复制与活继承**（2026-09-30，起草时）。风格和 TTS 默认值在创建项目时**复制**进项目，之后与设置页脱钩（和设计「创建项目时复制所选风格」一致）；联网模式和阶段默认模型是**运行时读取**的设置，改了下一轮生效。
- **D8 `style_presets` 新列叫 `reference_files`**（2026-09-30，T2）。计划写的是 `references`，但它是 SQL 保留字；数据库列名用 `reference_files`，对外（仓储值对象、API）仍叫 `references`。预设名字在仓储层强制唯一（去首尾空白后），导入的幂等也靠它。`created_at` 读回来统一补 UTC 时区（SQLite 丢时区信息）。
- **D12 「新项目默认音色/语速」放在语音页，不放通用页**（2026-09-30，T10）。计划 T10 把它写在通用页；T12 的语音页本来就要列音色、试听、设默认值，放两处会重复，所以只放语音页（T12 做）。通用页只有各阶段默认模型和联网模式。
- **D11 Claude 会话换模型先限制在同一种认证方式内**（2026-09-30，T7）。计划写的是「同 runtime 且同 provider，登录 ↔ key 互换不行再收紧」；互换要用 API key 付费实测，计划只预先授权了本机登录的冒烟（SOP §6 第 7 条），所以没有先放开再测，而是先按收紧后的规则上线，互换登记为 TD-41，验证后再放宽。OpenAI 及其他运行时不受这条限制（`SQLiteSession` 与模型、key 无关），只有 mock 测试。见 ADR 0012。
- **D10 模型配置接口现在返回环境变量名和网关地址**（2026-09-30，T6）。M1 T7 时刻意不返回 `api_key_env`；界面要编辑它就必须返回。返回的是环境变量的**名字**和 `base_url`（账号密码打码，写入时也拒绝带账号密码的地址），永远不返回 key 的值，`test_profiles.py` 里原来的「不泄露环境变量名」测试改成「不泄露 key 值」并新增打码断言。`name`/`provider`/`runtime` 建好后不可改（会话按它们判断能否换模型，T7）；环境变量决定的字段界面不让改（422 说明改 `backend/.env`）。
- **D9 旧字段名的提示不只针对金样本**（2026-09-30，T4）。真实数据显示 8 个叙事蓝图里 6 个（对应 7 个模板）提到旧系统的镜头字段名（`scene_index`、`beat_index`、`estimated_duration_seconds`），所有 5 个金样本都是旧格式。导入仍然不改写正文（D2），但入口 `STYLE.md` 的「旧格式提示」会点名受影响的文件，并写明 `narrative.json` 的字段以叙事阶段系统提示词为准。这条提示是否足够，由 T5 的真实冒烟判断；不够就在叙事提示词里加强，而不是改导入内容。
- **D7 默认风格的存在性校验推迟到 T2**（2026-09-30，T1）。T1 时风格库仓储还不存在，`default_style_preset_id` 只做形状校验；T2 建好仓储后补引用检查（已写进「下一步」），AC1 里「默认风格存在」这一项在 T2 才算完成。
- **D6 环境变量网关覆盖保持优先**（2026-09-30，起草时）。`seed_model_profiles` 对 `claude-sonnet`/`gpt` 的 `base_url`/`model`/单价，在环境变量非空时每次启动都会覆盖库里的值。本计划不改这个行为，界面把这些字段标只读并说明；如果以后想让界面覆盖环境变量，是独立的改动。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 起草时发现：`suggest_upstream_change` 写 `suggestions` 时 `turn_id` 恒为 `None`，不发 `suggestion` 事件，`api/sessions.py` 的 `WIRE_EVENT_TYPES` 也没有这个类型；前端没有任何读取建议的接口或界面。所以「完整体验」是从后端事件开始做的（T9），不只是加一个前端卡片。
- 起草时发现：`ProjectCreate.settings` 是任意 dict，`voice`/`speech_rate` 目前只有 `synthesize_tts` 读取，界面没有任何入口设置（创建项目对话框只有标题）。
- T4 实测：旧库共 9 个模板、34 个组件（叙事蓝图 8、配色 11、动画风格 10、金样本 5），没有悬空 id、没有类别不符；4 个组件没被任何模板引用（冷白学术图解·证据驱动、心理认知紫、语义驱动动态图解、高对比亮底认知紫）；「冷白学术图解·紫青语义」没有叙事蓝图，「暖白极简科普」「群像剧场」「记忆唤醒·理科卡片」没有金样本；不同模板共享同一个组件。所有金样本都是纯 JSON，但用旧系统格式。
- T4 注意：`data/` 在 worktree 里是 worktree 自己的目录（`.claude/worktrees/m5-polish/data`），导入的风格在合并到 main 之后不会自动出现在主检出的数据库里；收尾（T14）时在 main 上再跑一次 `make import-legacy-styles`（导出 JSON 可以从 worktree 的 `data/legacy-export/` 复制，或重新导出）。
- 起草时发现：旧项目风格组件在 Postgres 里，并且由 21 个 alembic 迁移逐步种入和改写；旧 dev DB 曾在 git 之外被改过（见 legacy-assets.md），所以导入以真实库为准而不是重放迁移。

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

证据目录：`data/evidence/m5-polish/`（不进 git；worktree 的 `data/` 在 `.claude/worktrees/m5-polish/data/`，走查和冒烟证据在主检出的同名目录）。

- **整体（AC12 的 `make check` 部分）**：评审修复后最终代码上 `make check` 全绿——后端 1367 passed（29 个冒烟用例默认不跑）、前端 vitest 376 passed，ruff、pyright、import-linter、eslint、vue-tsc、文档检查全部通过。
- **AC1**：`backend/tests/db/test_settings_repo.py`、`backend/tests/api/test_settings.py`、`backend/tests/agent/test_web_mode.py` 通过（含默认风格存在性校验、联网模式清除后回落环境变量、下一轮生效）。
- **AC2**：迁移 0004 在旧库上升级（`test_repo_style_presets.py` 里从 0003 升级的旧行用例）、仓储 CRUD 与校验、`workspace/style_files` 渲染、`api/test_styles.py` 通过。评审后追加：句末句号不算文件名、`description=null` 可清空、列表只查摘要列。
- **AC3**：`backend/tests/api/test_projects.py` 通过；L4：设置页导入 9 套旧风格后，创建项目对话框选风格，新项目 `style/` 下出现 5 个文件（截图 `l4/t11-*.jpg`）。
- **AC4**：`backend/tests/db/test_legacy_styles.py` 通过；真实导出与导入报告见 `t4-legacy-import.md`（9 个模板、34 个组件，导出连接只读）。
- **AC5**：提示词关键词断言通过；真实冒烟 `style_claude_login`（本机 Claude 登录，`smoke/20260930T131101Z-style-claude-login.json`）：叙事一轮在写 `narrative.json` 之前读了 `STYLE.md`、`narrative-blueprint.md`、`exemplars/`，动画一轮先读了配色和动画风格，产物都通过校验，都没有写 `style/`。只验证了「概念传记·纸上溯源」一套（TD-42）。
- **AC6**：`backend/tests/db/test_repo_profiles_crud.py`、`backend/tests/api/test_profiles.py` 通过。评审后追加：没改的 `base_url`（环境变量灌入、可能带账号密码）不再阻止其他字段的修改。
- **AC7**：`backend/tests/agent/test_model_switch.py`、`backend/tests/api/test_sessions.py` 通过；评审后追加：开跑即记录本轮配置，被崩溃中断的一轮不再让换模型提示重复。真实冒烟 `model_switch_claude_login`（`smoke/20260930T132106Z-*.json`）：Sonnet → Haiku，`sdk_ref` 不变、第二轮答得出第一轮的事实、`usage.model` 是 Haiku、时间线有 `model_switched`。L4 截图 `l4/t12-model-switcher.jpg`、`l4/t12-switch-notice-and-recall.jpg`。Claude 登录 ↔ API key 互换未验证（TD-41）。
- **AC8**：`backend/tests/api/test_tts.py`、`test_projects.py` 通过；真实试听 `tts_preview_real`（`smoke/20260930T132651Z-*.json` 与 5 个 mp3）：200、`audio/mpeg`、语速 0.5/2.0 被接受且时长方向正确、同组合第二次命中缓存；L4 语音页真实试听（`l4/t12-voice-page.jpg`，缺 key 的报错见 `l4/t12-preview-missing-key.jpg`）。
- **AC9**：`backend/tests/stages/test_suggest_upstream_change.py`、`backend/tests/api/test_suggestions.py`、`backend/tests/agent/test_runner_suggestion.py` 通过；真实冒烟 `suggestion_claude_login`（`smoke/20260930T140711Z-*.json`）：`suggestions` 表恰好一行（`narrative → topic`、`open`、记录了 `turn_id`）、会话里恰好一条持久的 `suggestion` 事件。
- **AC10**：vitest（`profileForm`、`settingsView`、`styleDraft`、`voiceRules` 等）通过；L4 走查（内置浏览器 + worktree 的 dev server）：模型配置增改删、环境变量字段只读（`l4/t10-*.jpg`）、通用页联网模式与默认模型、风格库编辑器（`l4/t11-style-editor.jpg`）、语音页。
- **AC11**：vitest（`suggestionFlow`、`useSessionStream` 归并、`modelChoice` 等）通过；L4：创建项目选风格、会话内换模型（真实 Claude 登录）、项目设置对话框、回退建议卡片 → 角标 → 去处理（确认重新打开）→ 预填 → 发送后标为已处理（`l4/t13-*.jpg`）。
- **评审（SOP §3 第 5 步）**：`code-review`（high，`main...m5-polish`）报 9 条。已修并加测试：句末句号被当成文件名（后端 + 前端）、被中断的一轮不记配置导致换模型提示重复、没改的带账号密码的 `base_url` 阻止其他字段编辑（后端 + 前端）、风格简介无法清空、风格列表与查重整表加载；已修但**未在浏览器复验**：通用页默认模型下拉在保存被拒后不回退（改动只有一处 `onError`，没有组件测试）。未修：TTS 试听接口无限流（合法组合有限、有缓存与同键合并，单人本地使用，不处理）；风格编辑器离开页面时无未保存提醒（登记 TD-43）；风格冒烟依赖被 gitignore 的导出文件且只覆盖一套（已是 TD-42）。
- **未验证**：Claude 登录 ↔ API key 互换（TD-41，需要 API 费用）；其余 8 套旧风格与弱模型的真实模型验证（TD-42）；OpenAI 托管搜索经 OpenRouter（TD-39）。
