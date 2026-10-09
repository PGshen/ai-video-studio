# remove-manim：移除 Manim 视频类型与相关依赖

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 待验收 |
| 里程碑 | 维护（系统瘦身） |
| 设计依据 | [架构设计](../../design/2026-09-26-architecture.md)、[ADR 0020](../../decisions/0020-阶段流水线按项目配置派生.md)、[ADR 0021](../../decisions/0021-HTML引擎与配乐阶段.md)；本计划新增 ADR 0027 记录"Manim 引擎下线"，已批准的设计文档不改，由 ADR 说明取代关系 |
| 分支 | `chore/remove-manim` |
| 批准记录 | 2026-10-09：负责人提出需求，并选定"老 manim 项目保留为只读"；2026-10-09：负责人批准计划 |

## 目标

实际使用中基本用不到 Manim 讲解视频。下线 Manim 引擎：新项目只能选 HTML 引擎；删掉 manim 阶段、渲染引擎、worker 渲染分支和 `manim`/`pyflakes` 依赖，环境搭建不再需要 cairo、pango、LaTeX。

## 范围

**包含：**

- 后端：`stages/pipeline.py` 不再提供 manim 预设和可选类型；项目创建拒绝 `engine=manim`；不带类型的创建请求默认改为 HTML 讲解。
- 删除 `stages/animation/`（manim 阶段、`validate_scenes`、`render_preview`、`rules.py`、提示词）和 `engines/render/manim/`；`worker.py` 只保留 HTML 渲染，遇到 manim 项目的成片任务直接以可读原因失败。
- `api/scene_checks.py`、`api/animation_stage.py`、`api/video_kinds.py`、`db/repo/settings.py`（各阶段默认模型）、`config.py`（`manim_timeout_seconds`）、`main.py`（注册表）中的 manim 分支。
- 老 manim 项目（设置里 `engine=manim` 或没有类型字段）**保留为只读**：照常列出、能看选题和叙事；`animation` 阶段不再注册，前端在该阶段显示"Manim 已下线"提示，不能对话、校验、预览或渲染。不做数据迁移，工作区文件原样保留。
- 测试：删除 manim 专属测试；把拿 manim `animation` 阶段当通用夹具的测试（`tests/fixtures/animation/seed.py`、`tests/agent/conftest.py`、`tests/smoke/support.py` 等）改用 `animation_html` 或其他阶段。
- 依赖：`pyproject.toml` 删 `manim`、`pyflakes`，更新 `uv.lock`；`slow` 标记说明去掉 manim。
- 前端：`Engine`/`VideoKind` 类型、类型选择、创建对话框默认值、测试夹具、工作台 `animation` 阶段改为下线提示、设置页默认模型列表。
- 文档：ADR 0027；`ARCHITECTURE.md`、`README.md`、`dev-setup.md`、`verification.md`、`QUALITY.md`、`tech-debt.md`、`TODO.md`、`references/README.md`；`references/manim.md` 标注"已下线，仅供历史参考"；`plans/todo/windows-native.md` 中依赖 manim 的任务和验收标准改写为 HTML 讲解。

**不包含：**

- 修改 `docs/design/` 中已批准的设计文档（由 ADR 0027 说明取代关系）。
- 删除或迁移现有 manim 项目的数据。
- 旧项目 `../ai-video` 中的任何文件。
- 删除 `numpy`、`pillow`：HTML 引擎、配乐等仍直接使用。

## 验收标准

- [ ] AC1：`GET /api/video-kinds` 不再包含 manim 预设和 manim 类型；`POST /api/projects` 传 `engine=manim` 返回 422；不带类型字段时创建出 HTML 讲解项目。（验证：API 测试）
- [ ] AC2：老 manim 项目能列出、读取设置和选题/叙事；对 `animation` 阶段发起对话返回明确错误；成片任务以"Manim 已下线"失败而不是崩溃。（验证：API/worker 测试；本地 dev 打开「一部剧前15集封神…」截图）
- [ ] AC3：`backend/src` 和 `frontend/src` 中没有对 `manim` 包、`pyflakes` 的 import，`studio.engines.render.manim`、`studio.stages.animation` 不再存在。（验证：`grep -rn "import manim\|pyflakes" backend/src` 为空）
- [ ] AC4：`pyproject.toml`、`uv.lock` 中没有 `manim`、`pyflakes`（以及只被它们依赖的包）；全新 `uv sync` 不需要 cairo/pango/LaTeX。（验证：`uv lock` 差异、`grep manim backend/uv.lock` 为空）
- [ ] AC5：前端新建项目对话框只出现 HTML 讲解、动态图形短片、音乐 MV；老 manim 项目的动画阶段显示下线提示。（验证：前端测试 + 浏览器截图）
- [ ] AC6：`make check` 全绿；`pytest -m slow` 中与 HTML/ffmpeg 相关的慢测试仍通过。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：流水线与 API 不再提供 manim（完成）

- **目标**：manim 从可创建的类型里消失，老项目仍可读。
- **涉及文件**：`stages/pipeline.py`、`api/video_kinds.py`、`api/projects.py`、`api/schemas.py`；对应测试 `tests/api/test_video_kinds.py`、`tests/api/test_projects.py`、`tests/stages/test_pipeline.py`。
- **接口与要点**：`Engine` 仍保留 `"manim"` 字面量用于解析已存数据（`kind_from_settings`、`LEGACY_KIND` 不变）；新增 `DEFAULT_KIND = ProjectKind("html", True, "none")` 用于不带类型的创建；`valid_kinds()`、`PRESETS` 去掉 manim；`unavailable_reason` 对 manim 返回"Manim 已下线"；创建时 `engine=manim` → 422。
- **测试**：先改测试断言上述行为并确认失败。
- **验证命令**：`make check`

### T2：删除 manim 阶段、引擎与 worker 分支（完成）

- **目标**：manim 相关代码全部删除，依赖它的通用测试夹具迁移到 `animation_html`。
- **涉及文件**：删除 `stages/animation/`、`engines/render/manim/`、`tests/engines/test_manim_*.py`、`tests/stages/test_animation_{validate,preview,prompt}.py`、`tests/fixtures/animation/`（视引用情况保留音频夹具）；修改 `main.py`、`worker.py`、`api/scene_checks.py`、`api/animation_stage.py`、`api/animation.py`、`agent/tools.py`、`config.py`、`db/repo/settings.py`、`stages/common/suggest_upstream_change.py`（`stages` 集合）；以及 `tests/agent/*`、`tests/smoke/support.py`、`tests/test_worker.py`、`tests/api/test_animation_*` 等夹具迁移。
- **接口与要点**：`worker.run_once` 对非 HTML 项目直接 `fail(..., "Manim 已下线，无法渲染成片")`；`animation_stage_of` 的回落值保留 `"animation"`（老项目只读）；`db/repo/settings.py` 去掉 `"animation"` 后，库里已存的该键读时忽略、不报错（加测试）；`suggest_upstream_change` 的阶段集合核对是否本应包含 `animation_html`/`produce`，按现状保留语义。
- **测试**：worker 对 manim 项目失败的测试；设置读取忽略旧键的测试；其余为删除和迁移。
- **验证命令**：`make check`

### T3：移除依赖（完成）

- **涉及文件**：`backend/pyproject.toml`、`backend/uv.lock`、`Makefile`（如有 manim 相关）。
- **要点**：删 `manim`、`pyflakes`，`uv lock` 后确认被一并移除的传递依赖没有被 `studio` 直接 import（当前直接 import 的第三方包已核对：numpy、PIL、librosa 等均为显式依赖）。
- **验证命令**：`cd backend && uv sync && make check`；`uv run pytest -m slow`

### T4：前端（完成）

- **涉及文件**：`frontend/src/types/api.ts`、`composables/videoKindChoice.ts`、`features/ideas/CreateProjectDialog.vue`、`test/videoKindsFixture.ts`、`pages/ProjectWorkbenchPage.vue`、`features/canvas/animation/*`、`features/canvas/stageActions.ts`、`features/settings/settingsView.ts` 及相关 spec。
- **要点**：类型保留 `'manim'`/`'explainer_manim'` 以显示老项目（标签"知识讲解（Manim，已下线）"）；创建默认 `explainer_html`；`stage === 'animation'` 显示下线提示，不再渲染 Manim 画布；去掉只服务 manim 的 `.py` 镜头路径逻辑。
- **验证命令**：`make check`；浏览器打开新建项目对话框和老项目截图。

### T5：文档与收尾（完成）

- **涉及文件**：ADR `docs/decisions/0027-下线Manim引擎.md`、`ARCHITECTURE.md`、`README.md`、`runbooks/dev-setup.md`、`runbooks/verification.md`、`quality/QUALITY.md`、`quality/tech-debt.md`、`plans/TODO.md`、`references/README.md`、`references/manim.md`、`plans/todo/windows-native.md`。
- **验证命令**：`make check`（含文档检查）

## 进度

- 2026-10-09 — T1 — `valid_kinds`/`PRESETS` 去掉 manim，新增 `DEFAULT_KIND`（HTML 讲解），`unavailable_reason` 对 manim 返回下线原因；创建 manim 项目 422。默认类型变化只让 4 个测试需要调整，`make check` 绿
- 2026-10-09 — T2 — 删除 `stages/animation/`、`engines/render/manim/`、`engines/render/base.py`（只服务 manim）；worker 只走 HTML，老项目任务以"Manim 已下线"失败；渲染/定稿端点对老项目 409；镜头检查只认 HTML 工具；默认模型设置读时丢弃 `animation` 键。测试夹具迁到 `animation_html`，`make check` 绿

- 2026-10-09 — T3 — 删 `manim`、`pyflakes`，`uv lock` 连带移除 25 个包（av、pycairo、manimpango、moderngl、pyglet、skia-pathops、pydub 等）；确认 `studio` 不直接 import 其中任何一个；`make check` 绿，`pytest -m slow` 66 passed
- 2026-10-09 — T4 — 删除 `AnimationCanvas.vue`；新建对话框只剩 HTML 讲解/短片/MV，默认 HTML 讲解；老项目动画阶段显示下线提示；镜头脚本路径固定 `.js`；设置页默认模型去掉 `animation`。另补后端：老项目 `animation` 阶段新建会话、发消息返回 409。`make check` 绿，浏览器实测见验证记录
- 2026-10-09 — T5 — ADR 0027；ARCHITECTURE、README、dev-setup、verification、QUALITY、references 更新；windows-native 计划去掉 manim/MiKTeX，讲解类验收改用 HTML。`make check` 绿

## 下一步

- 自验证（填「验证记录」），然后请评审者（新 subagent）评审整条分支，处理评审意见后请负责人验收。

## 决策记录

- 2026-10-09 — 一并删除 `engines/render/base.py`（`RenderEngine` 协议等）— 只有 manim 引擎和 worker 的 manim 分支在用，HTML 引擎不依赖它。
- 2026-10-09 — 渲染（`POST /render`）和成片定稿对老 manim 项目返回 409，worker 也兜底失败 — 阶段已不注册，提前给可读原因，避免任务排进队列后才失败。
- 2026-10-09 — `stage_default_profile` 去掉 `animation` 后，库里已存的该键读时丢弃而不是迁移 — 不需要数据迁移，写入时照常校验。
- 2026-10-09 — `fixtures/animation/` 保留：其中叙事产物（narrative/timing/音频）被 HTML、配乐等种子共用；`seed.py` 改为老 manim 项目种子，用来测只读行为。
- 2026-10-09 — `suggest_upstream_change` 的 `stages` 声明改为实际挂载它的阶段（narrative、music、animation_html、produce）— 该字段只是声明，原值里的 `animation` 已不存在。
- 2026-10-09 — 老 manim 项目保留为只读，不做数据迁移 — 负责人选择；只有 2 个此类项目，其中 1 个是可删除的验证项目。
- 2026-10-09 — `Engine` 类型保留 `"manim"` 字面量 — 只用于解析已存的项目设置，避免老项目被当成损坏数据。

## 意外与发现

- 2026-10-09 — 浏览器实测发现：老项目 `animation` 会话发消息时 `TurnRunner.start_turn` 的 `registry.get` 抛 KeyError → 500。已在 `api/sessions.py` 对该阶段的新建会话、发消息、继续返回 409（`test_sessions.py::TestRetiredManimStage`）。
- 2026-10-09 — 验证时 `make dev` 的 uvicorn 热重载卡住：旧进程等浏览器里的 SSE 长连接关闭才退出，期间 8000 端口不响应；离开项目页后恢复。和本计划无关的既有现象，记一笔供参考。

## 阻塞

- 无

## 验证记录

证据目录：`data/evidence/remove-manim/`（不进 git）。

- AC1 ✅ — `tests/api/test_video_kinds.py`、`tests/api/test_projects.py::TestCreateProjectKinds`（三张预设、5 种配置全为 html；`engine=manim` 422；不带类型字段建出 `explainer_html`）。实际运行的 api 上 `GET /api/video-kinds` 返回 presets `[explainer_html, motion_reel, music_video]`。
- AC2 ✅ — 测试：`test_worker.py::test_legacy_manim_project_job_fails_with_retired_reason`、`test_jobs.py::test_legacy_manim_project_is_409`、`test_animation_finalize.py::test_legacy_manim_project_cannot_finalize_render`、`test_html_render_flow.py::test_legacy_manim_project_can_neither_render_nor_finalize`、`test_scene_checks_endpoint.py::test_legacy_manim_project_reports_every_scene_as_not_checked`、`test_sessions.py::TestRetiredManimStage`、`test_repo_settings.py::test_retired_stage_defaults_are_ignored_on_read`。实测：本地老项目「一部剧前15集封神…」`GET /api/projects/{id}` 正常返回 `explainer_manim` 和三个阶段；`POST /render`、`POST /stages/animation/sessions` 都是 409「Manim 动画已下线…」；工作台动画阶段显示下线提示，历史会话可读（`legacy-animation-stage.jpg`）。
- AC3 ✅ — `grep -rnE "^\s*(import|from) (manim|pyflakes)" backend/src backend/tests` 无输出；`studio.engines.render.manim`、`studio.stages.animation` 已不存在。
- AC4 ✅ — `pyproject.toml` 与 `uv.lock` 中没有 `manim`/`pyflakes`/`pycairo`/`manimpango`；`uv lock` 移除 25 个包，`uv sync` 后 `make check` 绿。未在全新机器上验证"不装 cairo/pango/LaTeX 也能 `uv sync`"，依据是锁文件里已没有需要它们编译的包。
- AC5 ✅ — vitest（`VideoKindPicker.spec.ts`、`CreateProjectDialog.spec.ts` 等）；浏览器实测新建对话框只有三种类型、默认 HTML 讲解、流水线「选题 → 叙事 → 动画」（`create-dialog.jpg`，未提交创建）。
- AC6 ✅ — `make check` 全部通过（2026-10-09，T5 提交后）；`cd backend && uv run pytest -m slow`：66 passed。
