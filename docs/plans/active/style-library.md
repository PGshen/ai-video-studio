# style-library：风格库重构（侧栏入口、卡片列表、抽屉、磁盘目录存储、AI 对话改风格）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | M5 之后的独立改动（无里程碑编号） |
| 设计依据 | [风格库重构设计](../../superpowers/specs/2026-10-04-style-library-redesign-design.md)（2026-10-04 负责人确认）；取代 [ADR 0011](../../decisions/0011-风格库采用skill形态目录.md) 中的存储方式；[架构设计](../../design/2026-09-26-architecture.md) §3.1 的 `style_presets` 表描述因此过时，按红线不改该文件 |
| 分支 | `style-library-redesign` |
| 批准记录 | 2026-10-04：负责人批准设计文档；2026-10-04：负责人批准计划，执行方式为当前会话内联（Native） |

> **执行方式**：当前会话内联（2026-10-04 负责人指定 Native）。

## 目标

风格库成为侧栏一级菜单：卡片列表（筛选、分页），点卡片在右侧抽屉看详情，卡片上的编辑按钮直接进入编辑态；编辑态右侧嵌入 AI 对话区，AI 修改的是服务端草稿，用户确认「保存」后才成为正式版本。风格从 SQLite 改为纯磁盘目录存储，名称、简介、分类都在 `STYLE.md` 的 frontmatter 里。

## 范围

**包含：** 磁盘目录存储与草稿机制；`/api/styles*` 取代 `/api/style-presets*`；一次性迁移旧表数据；创建项目、旧项目导入脚本、默认风格设置改读目录；`sessions.subject_id` 与 `style` 阶段、`TurnRunner` 绑定目录模式；前端侧栏菜单、列表页、抽屉（详情态/编辑态）、对话区；ADR、架构文档、术语表更新；L4 浏览器走查和真实模型冒烟。

**不包含：** 草稿/正式版本的历史与回滚；多人协作和冲突合并；服务端筛选分页；agent 联网；已有项目里 `style/` 副本的任何改动（复制后与库脱钩，行为不变）。

## 全局约束

每个任务都隐含满足：

- 红线（AGENTS.md）：不改 `../ai-video`；不用 `skip`/`xfail`/`# type: ignore`/`noqa` 绕过失败；不引入计划外的新依赖（前端 `reka-ui`、`@vueuse/core`、`@lucide/vue`、`@tanstack/vue-query` 均已有）；不改 `docs/design/` 下已批准的设计；`data/` 不放进 uvicorn reload 监听范围；不在工作区里用 git。
- 测试先行：每个任务先写失败的测试并确认它失败，再实现。
- 后端分层（`backend/pyproject.toml` 的 import-linter 契约）：新模块 `studio.styles` 只依赖 `config`（与 `engines`、`search` 同为纯能力层，T1 补契约）；`db`、`workspace`、`agent`、`api` 可以 import 它；`agent` 不 import `stages`。
- 前端分层（`frontend/eslint.config.ts`）：`features/*` 之间不互相 import；`components/` 不 import `features/` 或 `pages/`；禁止 `../` 相对路径；单个 `.vue` 约 250 行以内；纯逻辑放 `.ts` 并配 `.spec.ts`；`components/ui`、`ai-elements` 是生成代码，不改。
- 文案用中文，代码标识符与注释用英文；提交格式 `<type>(<scope>): <中文说明>`；代码与计划更新放同一个 commit。
- 每个任务结束时 `make check` 为绿。
- 风格目录里的文件名与相对路径一律经过统一校验；任何读写都不能越出风格目录（含符号链接）。
- L4 在隔离数据目录和 8001/5174 端口上做，不碰负责人正在运行的 8000/5173 实例与真实数据（见 [verification.md](../../runbooks/verification.md)）。

## 验收标准

- [ ] AC1：风格以目录形式存放在 `data/styles/<id>/`，草稿在 `data/style-drafts/<id>/`；SQLite 里不再有 `style_presets` 表；旧表数据已按原 id 导出成目录，数量核对一致，重复启动不重复导出。（验证：迁移与存储单测、对一份旧库副本实跑）
- [ ] AC2：`/api/styles*` 全部接口可用，保存校验失败返回 422 逐条错误；有对话轮次运行时草稿写入、保存、放弃、删除返回 409；创建项目、设置里的默认风格、旧项目导入脚本都改读写目录，行为与改造前一致。（验证：API 测试 + `make check`）
- [ ] AC3：侧栏有「风格库」，`/styles` 是卡片列表，可按关键词、分类、是否默认筛选并分页；设置页不再有风格库 Tab，`/settings/styles` 重定向到 `/styles`。（验证：组件测试 + L4）
- [ ] AC4：点卡片在右侧抽屉打开只读详情；卡片编辑按钮直接以编辑态打开；URL query 保持抽屉状态，刷新可恢复；关闭抽屉不丢草稿，卡片显示「有未保存草稿」。（验证：组件测试 + L4）
- [ ] AC5：编辑态是「名称/分类/简介表单 + 文件树 + 代码编辑器 + 右侧对话区」；表单读写 `STYLE.md` frontmatter；编辑自动写草稿；保存/放弃/设默认/复制/删除可用。（验证：组件测试 + L4）
- [ ] AC6：在对话区让 AI 修改风格，agent 只在草稿目录内工作，改动实时出现在文件树和编辑器里（未保存状态）；轮次运行时编辑器与表单只读；保存后才变成正式版本，放弃则恢复。（验证：fake runtime 的 API/组件测试 + 用本机登录 Claude 的 `make smoke` + L4 截图）
- [ ] AC7：ADR（取代 0011）、`ARCHITECTURE.md`、`glossary.md`、`dev-setup.md` 已更新；`make check` 全绿；收尾清单（SOP §7）完成。

## 评审关注点

设计没有明说、但使用者很可能遇到的情况；每条都在对应任务里有测试。

1. 旧表里迁移前写入的行没有 frontmatter（`db/repo/style_presets.py` 文档明说读取不校验）：导出时用该行的 name、description、category 合成 frontmatter，而不是跳过或让迁移失败；名称重复的旧行逐条报告，不静默丢弃（T4）。
2. agent 或用户在草稿里制造非法内容——符号链接、`..` 路径、顶层多出的文件或目录、超大文件、非 UTF-8 内容、frontmatter 被删：保存返回 422 且正式版本不变，草稿保持原样；任何路径都不能写到风格目录之外（T2）。
3. 列表扫描遇到手工弄坏的目录（没有 `STYLE.md`、frontmatter 不合法）不能让整个列表接口 500；名称在保存时与别的风格重复（包括 AI 通过改 frontmatter 改成重名）得到明确的 409/422（T2、T3）。
4. 对话轮次运行时用户点保存、放弃、删除、关闭抽屉、切换风格；轮次失败或被取消后草稿停在半成品状态：写操作被 409 拒绝并有提示，草稿保留，用户仍可保存或放弃（T9、T10）。
5. 通过 URL 打开不存在或刚被删除的风格；删除默认风格；新建风格后从未保存就离开：显示「风格不存在」而不是空白或报错；默认设置被清除，创建项目退回占位 `STYLE.md`；从未保存的新建草稿在放弃时整个目录删除（T3、T5、T7）。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

交付分四个阶段，每个阶段结束时都能独立跑通 `make check`：T1–T4 后端存储，T5–T7 前端新页面（无对话），T8–T9 agent 与会话，T10–T11 对话接入与收尾。

### T1：styles 纯能力模块——校验与 frontmatter（待开始）

- **目标**：把风格校验从 `db/repo/style_presets.py` 搬成作用在「目录内容」上的纯函数，不依赖数据库；同时写 ADR 记录存储方式的变更。
- **涉及文件**：新建 `backend/src/studio/styles/{__init__,layout,validate}.py`；`backend/pyproject.toml`（新增 `studio.styles` 只依赖 `config` 的 import-linter 契约）；`backend/tests/styles/test_validate.py`；新建 `docs/decisions/0019-风格库改用磁盘目录存储.md`（含 ADR 必需章节，注明取代 0011 的存储部分）；ADR 0011 元信息标注「存储部分被 0019 取代」。
- **接口与要点**：
  - `layout.py`：常量 `ENTRY_NAME = "STYLE.md"`、`REFERENCES_DIR`、`EXEMPLARS_DIR`；`styles_root(data_dir)`、`style_dir(data_dir, style_id)`、`drafts_root(data_dir)`、`draft_dir(data_dir, style_id)`；`is_valid_style_id(id)`（只允许字母数字，防路径穿越）。
  - `validate.py`：`StyleFiles = dict[str, str]`（相对路径 → 文本，路径形如 `STYLE.md`、`references/x.md`、`exemplars/y.json`）；`parse_frontmatter(content) -> dict[str, str] | None`（沿用现有解析，含引号与转义）；`validate_style_files(files: Mapping[str, str]) -> list[str]`，规则从现有 `validate_style_preset` 原样迁移（名称取自 frontmatter `name`、≤100 字符；`description` 必填；`category` 可缺省；`STYLE.md` 必须有；每目录 ≤30 文件；文件名正则/长度/不以点开头/不重名；扩展名；`.json` 合法；入口引用的文件必须存在；单文件 ≤200000 字符），并新增：顶层只允许 `STYLE.md`、`references/`、`exemplars/`，其余路径一律报错。
  - 常量沿用 `MAX_FILE_CHARS` 等。
- **测试**：把 `backend/tests/db/test_repo_style_presets.py` 里的校验用例迁移过来并改成传文件映射；新增顶层多余文件、缺 `STYLE.md`、`category` 缺省三类用例。
- **完成标准**：纯函数测试全绿；import-linter 契约生效；ADR 通过 `scripts/check_docs.py`。此任务不删除旧代码。
- **验证命令**：`cd backend && uv run pytest tests/styles -q`；`make check`

### T2：目录存储与草稿（待开始）

- **目标**：在 `studio.styles` 里实现正式版本与草稿的全部目录操作，保存是原子的。
- **涉及文件**：新建 `backend/src/studio/styles/store.py`；`backend/tests/styles/test_store.py`。
- **接口与要点**：
  - 值对象：`StyleSummary(id, name, category, description, reference_count, exemplar_count, modified_at, has_draft)`；`StyleDetail(id, name, category, description, files: StyleFiles, modified_at)`。`category` 缺省返回「未分类」；列表里 `description` 缺省取 frontmatter。
  - 异常：`StyleNotFoundError`、`StyleValidationError(errors)`、`DuplicateStyleNameError`。
  - 正式版本：`list_styles(data_dir) -> list[StyleSummary]`（扫描 `styles/`，坏目录跳过并 `logger.warning`，不抛）、`get_style(data_dir, id) -> StyleDetail`、`read_style_files(data_dir, id) -> StyleFiles`（创建项目用）、`duplicate_style(data_dir, id) -> StyleDetail`（名称「原名（副本）」「（副本 2）」，沿用现有规则）、`delete_style(data_dir, id)`（同时删草稿）、`import_style(data_dir, files, *, style_id=None) -> StyleDetail`（校验后直接写正式版本，供迁移与导入脚本用，名称重复抛 `DuplicateStyleNameError`）。
  - 草稿：`create_new_draft(data_dir) -> str`（生成带模板的草稿，返回新 id，不进列表）、`open_draft(data_dir, id) -> DraftStatus`（没有就从正式版本复制，已有则幂等；正式版本不存在且无草稿抛 `StyleNotFoundError`）、`list_draft_files(data_dir, id) -> DraftStatus`、`read_draft_file`、`write_draft_file(data_dir, id, relpath, text)`、`delete_draft_file`、`discard_draft(data_dir, id)`（从未保存的新建草稿整个目录删除）、`save_draft(data_dir, id) -> StyleDetail`。`DraftStatus(id, is_new, dirty, files: list[str])`。
  - 保存：读取草稿全部内容 → `validate_style_files` → 名称与其他正式版本不重复 → 写入 `styles/<id>.tmp` → 与旧目录交换（rename）→ 删除草稿。只复制常规文件，遇到符号链接或越界路径一律视为非法（422）；失败时正式版本和草稿都不变。
  - 草稿文件读写复用 `studio.workspace.files` 的路径规则会形成 `styles → workspace` 依赖，违反契约，所以在 `studio.styles` 内自带一份小的路径安全函数（拒绝绝对路径、`..`、符号链接、隐藏文件）并单测。
- **测试**：列表扫描（含坏目录）、复制命名、打开草稿幂等、`dirty` 判断（改动后再改回原样为不脏）、保存成功/校验失败不改正式版本、保存过程中途失败（注入异常）后旧版本完整、草稿里的符号链接/`..`/多余顶层文件/超大文件/非 UTF-8 内容、改 frontmatter 名称成重名、放弃新建草稿删整个目录、路径穿越。
- **完成标准**：存储层纯文件系统实现，无数据库依赖；上述用例全绿。
- **验证命令**：`cd backend && uv run pytest tests/styles -q`；`make check`

### T3：`/api/styles` 接口，创建项目与默认风格改读目录（待开始）

- **目标**：新接口上线并与旧接口并存，创建项目、默认风格设置改用新存储。旧 `/api/style-presets` 暂时保留到 T4。
- **涉及文件**：重写 `backend/src/studio/api/styles.py` 为新接口（旧路由文件改名为过渡的 `style_presets_legacy.py` 暂存，T4 删除）；`backend/src/studio/api/schemas.py`（新增 `StyleSummaryOut`、`StyleOut`、`DraftStatusOut`、`DraftFileWrite`，旧 schema 暂留）；`backend/src/studio/api/projects.py`（`_style_for_new_project` 改读 `read_style_files`，仍写 `style/` 前缀）；`backend/src/studio/api/settings.py`（默认风格校验改查目录）；`backend/src/studio/main.py`（注册路由）；`backend/tests/api/test_styles.py`（重写）、`backend/tests/api/test_projects.py`、`backend/tests/api/test_settings.py`。
- **接口与要点**：路径与语义见设计文档 §3 的表。要点：
  - `POST /api/styles` 返回新草稿 id；列表接口返回 `StyleSummaryOut`（含 `is_default`、`has_draft`、`modified_at`）；`GET /api/styles/{id}` 返回正式版本全部文件。
  - 草稿文件接口 `GET/PUT/DELETE /api/styles/{id}/draft/files/{path:path}`，PUT body `{content}`，与项目文件接口风格一致；`GET /api/styles/{id}/draft/files` 返回 `DraftStatusOut`。
  - 错误映射：404 不存在，422 校验失败（detail 为逐条错误），409 重名。轮次运行的 409 在 T9 接入（接口里先留 `_ensure_not_busy(style_id)` 钩子，默认不拒绝）。
  - 所有会写目录的端点写成 `async def`（与项目文件接口同一理由，T9 要在事件循环上检查忙碌状态）。
  - 删除默认风格时清除 `settings.default_style_preset_id`；创建项目时请求指定的风格不存在 → 404，默认风格不存在 → 退回占位 `STYLE.md`。
- **测试**：新接口全部端点的成功与错误路径；评审关注点 3、5 中的重名与不存在、删除默认风格后创建项目；项目创建复制出的 `style/` 与目录内容一致且与库脱钩；设置里设不存在的默认风格 → 422。
- **完成标准**：新接口测试全绿；创建项目的既有测试不改断言仍通过。
- **验证命令**：`cd backend && uv run pytest tests/api -q`；`make check`

### T4：迁移旧数据、删除旧实现、导入脚本改写目录（待开始）

- **目标**：旧 `style_presets` 表的数据一次性导出成目录并删表；旧代码清理干净。
- **涉及文件**：新建 `backend/src/studio/db/legacy_style_table.py`（`export_style_table(engine, data_dir) -> ExportReport`，用原生 SQL 读旧表，不依赖 ORM 模型）；新建 `backend/src/studio/db/migrations/versions/0007_drop_style_presets.py`；`backend/src/studio/main.py`（lifespan 里在 `migrate(engine)` 之前调用导出）；删除 `backend/src/studio/db/repo/style_presets.py`、`backend/src/studio/workspace/style_files.py`、`backend/src/studio/api/style_presets_legacy.py`、`db/models.py` 里的 `StylePreset` 及对应旧 schema；改写 `backend/src/studio/db/legacy_styles.py` 的落库部分，改用 `studio.styles.store`；`Makefile`/`scripts/export_legacy_styles.sh`/`docs/runbooks/dev-setup.md` 里有关命令与说明；测试：`backend/tests/db/test_legacy_style_table.py`（新）、`test_legacy_styles.py`、`test_migrate.py`，删除 `test_repo_style_presets.py`、`tests/workspace/test_style_files.py`。
- **接口与要点**：
  - 导出：表不存在则什么都不做；每行目录名沿用旧 id；目录已存在则跳过（幂等）；用 `import_style` 的校验——旧行没有 frontmatter 或缺 `name`/`description` 时，用该行的 name、description、category 合成 frontmatter 再写；`category` 写进 frontmatter；同名行逐条记入报告，不静默丢弃；`ExportReport` 含 `exported`、`skipped_existing`、`synthesized_frontmatter`、`problems`；导出数量与表行数核对，不一致则抛错，启动失败而不是继续删表。
  - 迁移 0007：`DROP TABLE IF EXISTS style_presets`，不提供降级。因为导出在迁移之前，导出失败时迁移不会执行。
  - 导入脚本：行为与报告格式不变，「已存在」按目录里的名称判断，「覆盖」直接重写目录。
  - 运行手册里加一条：升级前备份 `data/studio.db`。
- **测试**：评审关注点 1（无 frontmatter 的行、缺 description 的行、重名行）；重复执行不重复导出；导出数量不一致时抛错且不删表；0007 在没有该表的新库上不报错；导入脚本既有用例迁移到新存储后仍通过。
- **完成标准**：代码库里不再有 `style_presets`/`StylePreset`/`render_style_files` 的引用（旧迁移 0001/0004 除外）；对一份旧库副本实跑导出，列出每套风格的目录和报告，附在「验证记录」。
- **验证命令**：`cd backend && uv run pytest -q`；`make check`

### T5：前端基础——菜单、路由、API 客户端与纯逻辑（待开始）

- **目标**：侧栏出现「风格库」，路由、类型、查询 hook、纯逻辑就绪，页面先是占位。
- **涉及文件**：`frontend/src/components/AppSidebar.vue`（`navMain` 在「项目」和「设置」之间加「风格库」）；`frontend/src/router.ts`（`/styles`，`/settings/styles` 重定向到 `/styles`，meta.title）；`frontend/src/pages/SettingsPage.vue`（移除风格库 Tab）；`frontend/src/api/endpoints.ts`、`frontend/src/types/api.ts`、`frontend/src/composables/queries.ts`（新增 `listStyles`、`getStyle`、`createStyle`、`duplicateStyle`、`deleteStyle`、`openStyleDraft`、`getStyleDraft`、`readDraftFile`、`writeDraftFile`、`deleteDraftFile`、`saveStyleDraft`、`discardStyleDraft` 及对应 query/mutation hook，key 统一在 `queryKeys.styles*`）；新建 `frontend/src/features/styles/styleView.ts`（`filterStyles`、`allCategories`、排序）、`styleFrontmatter.ts`（`parseFrontmatter`、`updateFrontmatter(content, patch)`，保持其余行不变，支持引号与转义）及两个 `.spec.ts`；新建 `frontend/src/pages/StylesPage.vue` 占位；`components/StyleSelect.vue`、`composables/styleChoice.ts` 改用新 hook。
- **接口与要点**：旧的 `listStylePresets` 等客户端函数与 hook 一并删除，所有引用点（创建项目对话框）改新接口；`useStylePresetsQuery` 的使用者按新类型调整。
- **测试**：`styleView.spec.ts`（关键词/分类/仅默认筛选、排序）、`styleFrontmatter.spec.ts`（读写三字段、缺省分类、没有 frontmatter 时补一个、值含冒号/引号）、路由重定向与侧栏菜单的组件测试。
- **完成标准**：`/styles` 可访问；设置页没有风格库 Tab；创建项目选风格仍可用。
- **验证命令**：`cd frontend && pnpm vitest run`；`make check`

### T6：风格库列表页（待开始）

- **目标**：卡片列表、顶部筛选、新建按钮、分页。
- **涉及文件**：`frontend/src/features/styles/StyleGrid.vue`、`StyleCard.vue`；`frontend/src/pages/StylesPage.vue`；对应 `.spec.ts`。
- **接口与要点**：布局与交互借 `features/ideas/IdeaGrid.vue` 的模式（顶部筛选栏、`grid-cols-[repeat(auto-fill,minmax(18rem,1fr))]`、底部 `ListPager`、`composables/pagination.ts`）；筛选：关键词、分类 Badge、「仅看默认」；卡片显示名称、分类、简介摘要、引用数/金样本数、「默认」Badge、「有未保存草稿」标记、编辑按钮；点卡片或编辑按钮只改 URL query（`?style=<id>&mode=view|edit`），抽屉在 T7 接入；「新建风格」调用 `createStyle` 后跳到 `?style=<新id>&mode=edit`；筛选变化时页码回到第 1 页。
- **测试**：筛选与分页、空列表和筛选无结果的提示、点击卡片与点击编辑按钮产生的 query、新建流程、草稿标记。
- **完成标准**：列表可用；组件测试全绿。
- **验证命令**：`cd frontend && pnpm vitest run src/features/styles`；`make check`

### T7：抽屉——详情态与编辑态（无对话）（待开始）

- **目标**：右侧抽屉打开详情（只读）和编辑（草稿），拆掉旧的设置页风格库组件。
- **涉及文件**：新建 `frontend/src/features/styles/{StyleDrawer,StyleDetailView,StyleEditView,StyleMetaForm,StyleFileTree}.vue`、`useStyleDraft.ts`（草稿查询、防抖写入、保存/放弃）及 `.spec.ts`；删除 `frontend/src/features/settings/{StylePresetsPanel,StylePresetEditor}.vue`、`styleDraft.ts` 及其测试；`frontend/src/pages/StylesPage.vue`（挂载抽屉，由 URL query 驱动）；复用 `components/CodeEditor.vue`、`components/ui/sheet`、`ConfirmDeleteButton`。
- **接口与要点**：
  - 抽屉用现有 `Sheet`，右侧滑出，宽度约 `min(96vw, 1400px)`；每个 `.vue` 不超过 250 行。
  - 详情态：名称/分类/简介、只读文件树与查看、按钮「编辑」「设为默认」「复制」「删除」；读的是正式版本。
  - 编辑态：进入时调用「打开草稿」；表单读写 `STYLE.md` 的 frontmatter（经 `styleFrontmatter.ts`）；文件树支持新增、删除文件（分 `references/`、`exemplars/`，沿用现有文件名规则提示）；编辑器输入后 600ms 防抖写草稿并显示保存状态；底部「保存」「放弃修改」，保存 422 的错误逐条显示，`data-testid` 沿用现有的 `save-style`、`style-server-error` 等命名。
  - 关闭抽屉保留草稿；放弃新建草稿后关闭抽屉并回到列表；URL 指向不存在的风格时显示「风格不存在」。
  - 编辑器和表单暴露 `readonly` 属性，T10 接入对话时由轮次状态驱动。
- **测试**：详情态与编辑态切换、表单改动写入 frontmatter、防抖写草稿、保存成功与 422 展示、放弃、关闭保留草稿、不存在的 id、设为默认/复制/删除、新增与删除文件。
- **完成标准**：不含对话的完整编辑流程可用；旧设置页组件和 `styleDraft.ts` 已删除，`make check` 绿。
- **验证命令**：`cd frontend && pnpm vitest run src/features/styles`；`make check`；L4：列表、详情、编辑三张截图（由控制者在 8001/5174 上做）。

### T8：会话归属 `subject_id` 与风格会话接口（待开始）

- **目标**：会话可以属于一套风格；创建会话与活动会话切换按 `项目 + 阶段 + subject_id` 区分。
- **涉及文件**：新建 `backend/src/studio/db/migrations/versions/0008_sessions_subject_id.py`；`backend/src/studio/db/models.py`（`Session.subject_id` 可空）；`backend/src/studio/db/repo/sessions.py`（`SessionValue.subject_id`；`create_session(..., subject_id=None)` 的「取消同组活动」条件加入 `subject_id`；`list_sessions(engine, project_id, stage, subject_id=None)`）；`backend/src/studio/api/styles.py`（`POST/GET /api/styles/{id}/sessions`，风格必须存在，模型配置与运行时检查沿用 `brainstorm.py` 的写法）；`backend/src/studio/api/schemas.py`（`SessionOut.subject_id`）；`backend/tests/db/test_repo_sessions.py`、`backend/tests/api/test_styles.py`、`backend/tests/db/test_migrate.py`。
- **接口与要点**：风格会话的 `project_id=None`、`stage="style"`、`subject_id=<style id>`；头脑风暴会话的 `subject_id` 保持 `None`，两者互不影响活动状态；风格被删除时同时清理它的会话与草稿（沿用 `delete_project_sessions` 的模式新增 `delete_subject_sessions`）。此任务里 `style` 阶段尚未注册，所以创建接口先只做数据层与接口，T9 注册阶段后才能发消息。
- **测试**：同风格新建会话使旧会话取消活动、不同风格互不影响、与头脑风暴互不影响、`subject_id` 往返、迁移升级与降级不破坏现有数据、删除风格清理会话。
- **完成标准**：既有会话与头脑风暴测试全绿，不改断言。
- **验证命令**：`cd backend && uv run pytest tests/db tests/api -q`；`make check`

### T9：`style` 阶段与 `TurnRunner` 绑定目录模式（待开始）

- **目标**：在风格会话里发消息，agent 以草稿目录为工作目录修改文件；运行期间草稿写操作被 409 拒绝。
- **涉及文件**：新建 `backend/src/studio/stages/style/{__init__,prompt.md,tools.py}`；`backend/src/studio/agent/runner.py`（`_execute` 分支：`job.session.subject_id` 非空时走新的 `_execute_bound_dir`）；`backend/src/studio/agent/turn_state.py`（`busy_key` 对风格会话返回 `style:<subject_id>`）；`backend/src/studio/agent/turn_finish.py`（风格会话不删 scratch 也不动草稿目录，只发 `workspace_changed`）；`backend/src/studio/main.py`（注册 `STYLE_STAGE`）；`backend/src/studio/api/styles.py`（接入 `_ensure_not_busy`：新增 `TurnRunner.is_busy_key(key)` 供各写端点使用）；`backend/src/studio/api/settings.py` 与 `frontend/src/features/settings/settingsView.ts`（`stage_default_profile` 接受 `style`）；测试：`backend/tests/agent/test_runner_style.py`、`backend/tests/stages/test_style_stage.py`、`backend/tests/api/test_styles.py`、`backend/tests/api/test_sessions.py`。
- **接口与要点**：
  - `StyleStage`：`name="style"`、`allow_web=False`、`workspaceless=True`（没有项目）；`write_scope()` 为草稿目录内全部可写（实现时先确认 `WriteScope` 通配语义，补一条用例证明 `STYLE.md`、`references/*`、`exemplars/*` 可写而越界路径被拦）；`upstream_stages()`、`artifact_dirs()` 为空；`status_summary` 返回草稿简述。
  - 绑定目录模式：`workdir = draft_dir(data_dir, subject_id)`；开始前确保草稿存在（没有就 `open_draft`；风格已被删除则本轮 `failed`）；不做快照、`upstream/`、前言、越界检查；每次工具写文件后与轮次结束时发 `workspace_changed`（沿用现有事件）。
  - 工具 `validate_style`（无参数）：读取草稿目录，返回 `validate_style_files` 的错误列表或「校验通过」；工具上下文里需要 `workdir`，由此推出草稿内容，不碰数据库。
  - `prompt.md`：说明目录结构、frontmatter 三字段、「STYLE.md 要索引每个文件并写明什么时候读」、文件命名规则、只允许改草稿目录、改完调用 `validate_style`、不要动名称之外无关的内容；对照 ADR 0011 里各阶段读取约定保持一致。
  - 草稿的写入、删除、保存、放弃、打开草稿、删除风格在该风格有排队或运行中的轮次时返回 409「AI 正在修改，请稍候」。
- **测试**：用 `agent/fake.py` 的 fake runtime——风格会话一轮执行后草稿被改写且正式版本不变；同一风格的两个会话串行、不同风格并行、与项目轮次互不阻塞；运行期间各写端点 409、结束后恢复；风格在轮次开始前被删除；越界写入被拦；`validate_style` 对合法与非法草稿的输出；取消与失败后草稿保留。
- **完成标准**：风格会话在 fake runtime 下端到端可跑；既有 runner、头脑风暴测试不改断言全绿。
- **验证命令**：`cd backend && uv run pytest tests/agent tests/stages tests/api -q`；`make check`；真实模型冒烟放在 T11。

### T10：前端接入对话区（待开始）

- **目标**：编辑态右侧出现对话区，AI 的改动实时反映到编辑器。
- **涉及文件**：`frontend/src/composables/sessionScope.ts`（`{kind:'style', styleId}`）；`frontend/src/composables/queries.ts`（`sessionsFor`/`useSessionsQuery`/`useCreateSessionMutation` 的风格分支）；`frontend/src/api/endpoints.ts`（风格会话创建与列表）；`frontend/src/components/session/useEnsureSession.ts`（`stageKey` 为 `style`，用 `stage_default_profile.style` 预选模型）；`frontend/src/composables/useSessionStream.ts`（风格作用域下收到 `workspace_changed`/文件类 tool_result 时失效该风格的草稿文件树与当前文件查询）；`frontend/src/components/session/toolPresentation.ts` 与 `activity/tool-bodies`（`validate_style` 展示）；`frontend/src/features/styles/StyleEditView.vue`、`StyleChatPane.vue`（新建，`SessionPanel` + `SessionPicker` + `ModelSwitcher` 的组合，仿 `features/ideas/BrainstormDrawer.vue`）；`frontend/src/features/settings/settingsView.ts`（通用设置里加 `style` 阶段默认模型）；测试：`useSessionStream` 的风格分支、`StyleEditView` 轮次运行时只读、`StyleChatPane`。
- **接口与要点**：右栏约 24rem，抽屉在编辑态内部分为「表单+文件树+编辑器」与对话区两栏；轮次运行期间编辑器、表单、保存、放弃、新增删除文件全部禁用并提示「AI 正在修改」，轮次结束后刷新草稿并恢复；对话组件只从 `components/session/` 引入；抽屉在详情态不挂载对话区；关闭抽屉时对话区若有运行中的轮次，保持 SSE 连接直到轮次结束（沿用 `BrainstormDrawer` 的 `v-show` 保持挂载思路，仅限风格抽屉本身未卸载时）。
- **测试**：评审关注点 4（轮次运行时用户操作被禁用并有提示；轮次失败后草稿保留且按钮恢复）；AI 写文件后文件树与编辑器刷新；首次发送前自动创建会话并预选默认模型。
- **完成标准**：编辑态下用 fake runtime 能完整走一遍「对话 → 草稿变化 → 保存」。
- **验证命令**：`cd frontend && pnpm vitest run`；`make check`

### T11：文档、真实模型冒烟与 L4 走查（待开始）

- **目标**：文档与实现一致，真实模型下 AI 改风格可用，浏览器走查留证据。
- **涉及文件**：`docs/ARCHITECTURE.md`（后端模块表加 `styles`，`db`/`workspace`/`api`/`agent`/`stages` 相关描述，前端 `features/styles/`、`features/settings/` 的变化）；`docs/glossary.md`（风格、草稿、正式版本）；`docs/runbooks/dev-setup.md`、`docs/runbooks/verification.md`（风格库验证步骤、升级前备份提示）；`docs/quality/QUALITY.md`；`backend/tests/smoke/test_smoke.py`（新增风格对话冒烟用例，走本机 Claude 登录）；本计划的验证记录。
- **接口与要点**：冒烟用例：创建一套风格草稿，发「把简介改成……并新增一个 references 文件」，断言草稿内容变化且正式版本未变，再保存后正式版本更新；运行方式 `make smoke SMOKE_ARGS="-k claude_login"`（不产生 API 费用，不需要事先询问，见 SOP §6 第 7 条例外）。L4 由控制者在 8001/5174 隔离实例上完成：列表（含筛选、分页）、详情抽屉、编辑抽屉、对话改风格并保存、窄屏表现。
- **测试**：文档检查 `scripts/check_docs.py`；冒烟用例通过。
- **完成标准**：AC1–AC7 全部勾选并在「验证记录」里附证据；计划状态改为「待验收」。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k claude_login"`

## 进度

- 无

## 下一步

- 等负责人批准计划并指定执行方式；批准后从 T1 开始：先写 `backend/tests/styles/test_validate.py`，再建 `backend/src/studio/styles/` 与 import-linter 契约。

## 决策记录

- 2026-10-04 — 目录存储模块做成只依赖 `config` 的纯能力层 `studio.styles`，而不是放进 `workspace` — `db/legacy_styles.py` 和旧表导出在 `db` 层，`db` 不能 import `workspace`（分层规则）；纯能力层让 `db`、`workspace`、`agent`、`api` 都能用。
- 2026-10-04 — 旧表导出放在 lifespan 里 `migrate()` 之前，迁移 0007 才删表 — 迁移里拿不到数据目录；导出失败则启动失败，迁移不会执行，数据不会丢。
- 2026-10-04 — 风格会话复用 `workspaceless` 阶段标记，靠 `sessions.subject_id` 区分绑定目录模式 — 避免给 `StageDefinition` 协议加字段而改动全部阶段。
- 2026-10-04 — 迁移后目录 id 沿用旧表 id，新建的用 `uuid4().hex` — 与旧表 `_new_id` 一致，免去对 `default_style_preset_id` 和项目记录的映射。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 无
