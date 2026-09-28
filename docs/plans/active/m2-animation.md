# M2：动画阶段（代码 + 成片）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已批准 |
| 里程碑 | M2 |
| 设计依据 | [架构设计 §5.3、§10](../../design/2026-09-26-architecture.md) |
| 分支 | `m2-animation` |
| 批准记录 | 2026-09-28：负责人批准计划，执行方式为 subagent 驱动开发 |

## 目标

用户能在一个项目里（叙事阶段用手工准备的 fixture 顶替，因为 M3 未实现）打开动画阶段：让 agent 编写 `animation/scenes/<scene_id>.py`，用 `validate_scenes` 静态校验、用 `render_preview` 低清预览单个镜头并看到关键帧和配音时长偏差；用户点击"渲染成片"后 worker 在后台以最终画质渲染并合成音频字幕，用户能下载/预览 `output/final.mp4` 并"成片定稿"。

## 范围

**包含：**

- `engines.render`：manim 引擎迁移（静态校验 + 全画质渲染），新增 `render_preview`（单镜头低清预览 + 按 beat 抽取关键帧 + 时长偏差）。
- `jobs` 模块：SQLite 任务队列（领取、心跳、进度、结果）。
- `worker` 进程：领取 `final_render` 任务，逐镜头渲染、合成音频、加字幕、拼接，写 `output/final.mp4`/`output/final.json`；接入 `make dev`。
- `stages.animation`：`validate_scenes`、`render_preview(scene_id)` 工具，系统提示词（代码规则、风格组件写法、引擎约束、镜头合并约定）。
- `stages.common`：`suggest_upstream_change` 工具与 `suggestions` 仓储（基础功能，完整 UI 体验留到 M5）。
- 手工叙事 fixture：绕过未实现的 M3，提供 `narrative.json`/`timing.json`/音频样例，供开发和测试解锁动画阶段。
- api：创建/查询 `final_render` 任务、下载成片、"成片定稿"。
- 前端 `features/canvas/animation/`：镜头列表（已渲染/已过期/校验失败）、代码编辑器（复用 `CodeEditor.vue`）、预览视频与关键帧条、成片面板（进度、播放器、定稿按钮）。

**不包含：**

- M3 叙事阶段本身（agent 真正生成 `narrative.json`、`synthesize_tts`、`validate_narrative`、beat 对齐）——本计划只消费手工 fixture。
- 按镜头 id 的上游变更摘要（design §5.4 提到的"新增/删除/旁白变化/beat 变化"级别对比）：`preamble.py` 目前是 M1 定的文件级 diff，本计划不升级，等 M3 真有 narrative agent 时再做。
- `suggest_upstream_change` 的完整用户体验（对话卡片高亮、阶段导航角标、"去处理"跳转预填）：本计划只做工具本身和仓储，UI 呈现在 M5。
- 风格库/范例完整体验（M5）、选题/搜索（M4）。
- worker 多进程/多副本并发领取的强一致性：M2 只跑单个 worker 进程，`jobs` 的领取查询按"能防单进程内竞态"设计即可，不做分布式锁验证。

## 验收标准

- [x] AC1：`ManimRenderEngine.validate_code` 和 `.render` 在新代码路径下通过（渲染一个极小的手写镜头，得到 mp4）（验证：`pytest backend/tests/engines/test_manim_engine.py`）
- [x] AC2：`render_preview(scene_id)` 对一个两镜头的 fixture，返回每个 beat 的关键帧图片、渲染时长与配音时长的偏差；120 秒超时能被触发并返回工具错误而不是挂起整轮（验证：`pytest backend/tests/engines/test_manim_preview.py`）
- [x] AC3：`jobs` 仓储的领取语义防止同一任务被并发领取两次；心跳过期的 `running` 任务在 worker 启动时被标记 `failed`（验证：`pytest backend/tests/jobs/`）
- [ ] AC4：手工 fixture 项目上，从"叙事已定稿"状态开始，animation agent（`FakeRuntime`）跑一轮，调用 `validate_scenes` 和 `render_preview` 都能拿到预期结果；点击"渲染成片"后 worker 产出 `output/final.mp4` + `output/final.json`，"成片定稿"后阶段状态变 `finalized` 且项目标记完成（验证：`pytest backend/tests/api/test_animation_flow.py`，慢测试单独跑）
- [ ] AC5：`animation` 阶段的 `suggest_upstream_change` 工具调用后 `suggestions` 表新增一条 `status=open` 的记录（验证：`pytest backend/tests/stages/test_common.py`）
- [ ] AC6：前端动画画布能显示镜头列表、代码编辑器、预览关键帧和渲染成片进度/播放器（验证：`make dev` 手动走查 + `pytest frontend`；截图见「验证记录」）
- [ ] AC7：`make check` 全绿，包含新增的 import-linter 契约（`engines`/`jobs`/`worker` 层）

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：`engines.render` 协议与 manim 引擎迁移——静态校验 + 全画质渲染（完成）

- **目标**：`backend/src/studio/engines/render/` 下有可用的 `RenderEngine` 协议和 manim 实现，覆盖静态校验和全画质渲染（不含 T2 的预览能力）。
- **涉及文件**：
  - 新建 `backend/src/studio/engines/__init__.py`（空包）、`backend/src/studio/engines/render/__init__.py`（导出 `RenderEngine`、`EngineRegistry`、`SceneInput`、`RenderRequest`、`RenderResult` 等）。
  - 新建 `backend/src/studio/engines/render/base.py`：从 `../ai-video/backend/app/engines/render/base.py` 迁移 `SceneAudio`/`SceneInput`/`RenderRequest`/`RenderResult`/`RenderEngine` Protocol/`EngineRegistry`；`RenderEngine` 协议新增 `render_preview` 方法签名（T2 实现，本任务只声明）。
  - 新建 `backend/src/studio/engines/render/format.py`：迁移 `../ai-video/backend/app/video_format.py`（画幅/分辨率）。
  - 新建 `backend/src/studio/engines/render/manim/`（包，而不是单文件）：源文件 `../ai-video/backend/app/engines/render/manim.py`（836 行）按职责拆成 `script.py`（AST 变换：`_TexStringNormalizer`、`_ManimImportStripper`、`_RateFuncRewriter`、`_TexTemplateInjector`、`_hoist_scene_imports`、`_promote_cross_scene_names`、`_scene_line_ranges`、脚本拼接）、`process.py`（子进程执行、进度条/ANSI 清理、traceback 定位到镜头号）、`engine.py`（`ManimRenderEngine` 类：`validate_code`、`render`、`health_check`，实现 `RenderEngine` 协议）；`__init__.py` 导出 `ManimRenderEngine`。原文件已经较大且 T2 还要再加 `render_preview`，先按职责拆分，避免继续膨胀成一个文件（决策记录 D1）。
  - `backend/tests/engines/test_manim_engine.py`（新建；迁移 `../ai-video/backend/tests/test_manim_render_engine.py` 里静态校验和 `render` 相关用例，路径和 import 改成新结构）。
- **接口与要点**：
  - manim 是重依赖（cairo/pango/ffmpeg/LaTeX），迁移时不改动生成/校验/渲染逻辑本身，只改 import 路径和模块边界；`app.config.settings` 换成 `studio.config.get_settings()`。
  - `EngineRegistry` 在 `main.py` 装配时注册 `ManimRenderEngine`（本任务不接 `main`，留到 T7/T10 需要用到引擎时再注册，先让引擎和测试独立可用）。
  - `pyproject.toml` 加 `manim`、`pyflakes` 依赖（版本对齐 `../ai-video/backend/pyproject.toml`）；渲染类测试标记为慢测试（沿用 `make check` 现有的慢测试筛选约定，如果还没有就新增一个 pytest marker，写进决策记录）。
  - `ARCHITECTURE.md` 补 `engines.render` 的 import-linter 契约（只依赖 `config`）。
- **测试**：静态校验通过/失败（含 AST 修复路径）；`render` 渲染一个手写的极简两镜头脚本得到 mp4 文件；traceback 能定位回具体镜头号。
- **完成标准**：`pytest backend/tests/engines/test_manim_engine.py` 通过；`make check` 全绿（import-linter 新契约生效）。
- **验证命令**：`make check`

### T2：`engines.render` 预览渲染与关键帧抽取（完成）

- **目标**：`ManimRenderEngine.render_preview(scene_id, ...)` 能低清渲染到某个镜头为止、按该镜头每个 beat 的结束时刻抽取关键帧图片，并给出渲染时长与配音时长的偏差；120 秒超时返回明确错误而不是挂起。
- **涉及文件**：`backend/src/studio/engines/render/manim/engine.py`（加 `render_preview`）、新建 `backend/src/studio/engines/render/manim/keyframes.py`（ffmpeg 抽帧）、`backend/src/studio/engines/render/base.py`（Protocol 补充签名 + 新数据类）、`backend/tests/engines/test_manim_preview.py`（新建）。
- **接口与要点**：
  - 签名（放进 `base.py`）：`PreviewRequest`（`scenes: list[SceneInput]`（0..scene_index，沿用 T1 的合并脚本方式）、`target_scene_index: int`、`beat_end_times: list[float]`（目标镜头内各 beat 结束时刻，相对该镜头起点）、`audio_duration_seconds: float | None`）、`PreviewResult`（`success`、`error_message`、`render_duration_seconds`、`duration_deviation_seconds: float | None`、`keyframes: list[PreviewKeyframe]`（`beat_index`、`png_bytes`）、`render_log`）。
  - 实现思路：复用 T1 的合并脚本构建逻辑，只拼到 `target_scene_index`（丢弃更晚的镜头），用低分辨率/低 fps 渲染出一段连续视频（复用同一套 `_scene_N()` 顺序调用约定，见 `../ai-video/backend/app/engines/render/manim.py:801-812`）；目标镜头在合并视频里的起始偏移 = 之前各镜头 `SceneInput.audio.duration_seconds` 之和；用 ffmpeg 在 `起始偏移 + beat_end_time` 处抽帧（`keyframes.py` 封装 `ffmpeg -ss <t> -i <video> -frames:v 1 -f image2pipe -`）。
  - 时长偏差 = 目标镜头渲染出的实际时长（合并视频总时长 − 起始偏移）− `audio_duration_seconds`（为 `None` 时不给偏差）。
  - 超时：`asyncio.wait_for(..., timeout=120)`，超时杀掉 manim 子进程（`process.terminate()` 后 `kill`），返回 `success=False, error_message="预览渲染超时"`（不抛异常，调用方——T8 的工具 handler——转成 `ToolResult(is_error=True)`，设计 §6 表"预览渲染超时"行）。
  - 关键帧图片走 `RenderEngine` 层返回 `bytes`（PNG），T8 的工具 handler 再包成 `studio.agent.events.ImageData`——引擎层不依赖 `agent`。
- **测试**：两镜头 fixture（极简 manim 代码）渲染，验证关键帧数量等于 beat 数、每张图非空；`audio_duration_seconds` 给定时偏差计算正确；用一个会挂起的脚本（`while True: pass` 等价物或 `time.sleep`）验证超时路径能在 ~120s 测试太慢，改成对 `render_preview` 注入可配置超时参数或 mock 子进程验证超时分支被触发，不在测试里真等 120 秒。
- **完成标准**：`pytest backend/tests/engines/test_manim_preview.py` 通过。
- **验证命令**：`make check`（渲染类测试若标记为慢测试，另跑 `pytest backend/tests/engines -m slow`）

### T3：`jobs` 模块——SQLite 任务队列（完成）

- **目标**：`studio.jobs` 提供创建、领取、心跳、进度更新、完成/失败、查询的仓储函数，基于已存在的 `Job` ORM（`backend/src/studio/db/models.py:158`，M1 已建表）。
- **涉及文件**：新建 `backend/src/studio/jobs/__init__.py`、`backend/src/studio/jobs/repo.py`；`backend/tests/jobs/test_repo.py`（新建）。
- **接口与要点**：
  - `create_job(engine, *, type: str, project_id: str, payload: dict) -> JobValue`：初始 `status="queued"`。
  - `claim_next(engine, *, type: str) -> JobValue | None`：单条 `UPDATE jobs SET status='running', heartbeat_at=now() WHERE id = (SELECT id FROM jobs WHERE type=? AND status='queued' ORDER BY created_at LIMIT 1) RETURNING *` 效果（SQLite 用 `session_scope` 里先 `SELECT ... FOR UPDATE` 等价的短事务：查到一行立刻在同一事务内把状态改掉再提交，防止同进程内两次领取拿到同一行；决策记录 D2 说明为什么不追求跨进程强一致）。
  - `heartbeat(engine, job_id: str) -> None`：更新 `heartbeat_at`。
  - `update_progress(engine, job_id: str, progress: float) -> None`。
  - `complete(engine, job_id: str, *, result: dict) -> JobValue`：`status="done"`。
  - `fail(engine, job_id: str, *, error: str) -> JobValue`：`status="failed"`。
  - `get_job(engine, job_id) -> JobValue | None`、`list_jobs(engine, project_id, type=None) -> list[JobValue]`。
  - `reap_stale_running(engine, *, type: str, heartbeat_timeout_seconds: float) -> list[JobValue]`：把 `status="running"` 且 `heartbeat_at` 超过阈值的任务标记 `failed`（worker 启动时调用，design §6 表"worker 崩溃"行）。
  - `JobValue`：不泄露 ORM 对象（ARCHITECTURE 规则 5），字段对应 `Job` 表列。
- **测试**：创建后能领取一次、第二次领取返回 `None`（队列已空）；心跳/进度更新生效；`reap_stale_running` 只影响超时的 `running` 任务，不影响新鲜心跳的。
- **完成标准**：`pytest backend/tests/jobs/` 通过。
- **验证命令**：`make check`

### T4：手工叙事 fixture 与开发种子脚本（完成）

- **目标**：在没有 M3 narrative agent 的情况下，能创建一个"叙事阶段已定稿"的项目，用于本计划其余任务的测试和 `make dev` 手动走查。本任务提前到 T5/T7/T8 之前，因为那几个任务的测试都要读这个 fixture 项目（原排序把它放在 T9，会导致 T6/T7 写测试时无项目可用；调整记入决策记录 D6）。
- **涉及文件**：新建 `backend/tests/fixtures/animation/narrative.json`、`backend/tests/fixtures/animation/timing.json`、`backend/tests/fixtures/animation/audio/*.wav`（用 `numpy`/标准库生成的静音或简单正弦波 wav，不依赖任何外部 API 或付费调用，脚本化生成，不手工录音）、新建 `backend/tests/fixtures/animation/seed.py`（供测试用的 helper 函数）、`backend/tests/conftest.py` 或 `backend/tests/api/conftest.py`（加一个 `animation_project` fixture，若判断放这里更合适）。
- **接口与要点**：
  - `narrative.json`：2 个镜头（`s-hook`、`s-explain`），每个 2 个 beat，字段齐全（`id`/`narration`/`visual_intent`/`beats[].{cue_text,visual_action,emphasis,transition}`），符合设计 §5.2 的 schema 描述。
  - `timing.json`：对应的音频哈希（占位，实际由 wav 文件内容算）、`duration_seconds`、逐字时间戳（可以是简化的假数据，只要 `render_preview` 用得到的字段——beat 起止时间、音频路径、总时长——是真的）、对齐覆盖率（填 1.0）。
  - `seed.py` 提供 `seed_animation_project(engine, blobs, *, data_dir) -> project_id`：建项目 → 写 `narrative/narrative.json`、`narrative/timing.json`、`narrative/audio/*.wav`（用 `workspace.files`）→ `stage_flow.finalize(engine, blobs, registry, project_id, "narrative")`，让 `animation` 阶段从 `locked` 变 `active`。
  - 决策记录 D3：fixture 音频用脚本生成的静音/正弦波 wav，不追求听感真实；这是"手工准备的叙事 fixture"里的"音频"部分，因为 TTS 是 M3 范围，M2 不能依赖真实 TTS 输出。
- **测试**：`seed_animation_project` 之后 `get_stage(engine, project_id, "animation").status == "active"`；`upstream/narrative/` 下能读到 fixture 内容（走 `workspace.upstream` 的物化逻辑）。
- **完成标准**：`pytest` 里依赖这个 fixture 的用例（T5/T7/T8 的测试）都能拿到预期的项目状态。
- **验证命令**：`make check`

### T5：`worker` 进程与 `make dev` 接入（完成）

- **目标**：`backend/src/studio/worker.py` 是独立进程入口：循环领取 `final_render` 任务，用 T1/T2 的引擎逐镜头全画质渲染、合成音频、加字幕、拼接，写 `data/projects/<id>/output/final.mp4` 和 `output/final.json`；`make dev` 同时起 worker。
- **涉及文件**：`backend/src/studio/worker.py`（新建）、`backend/src/studio/jobs/*`（T3 产物）、`scripts/dev.sh`（去掉"worker 留到 M2"注释，加一段起 worker 的代码，仿 api 那段的 PID 收集/cleanup）、`Makefile`（`dev` 目标说明更新）、`backend/tests/test_worker.py`（新建，慢测试）。
- **接口与要点**：
  - 主循环：`reap_stale_running` 一次 → 轮询 `claim_next(type="final_render")`（无任务时 `asyncio.sleep(间隔)`）→ 领到后按 `payload` 里的 `project_id` 读工作区（`workspace.files`/`workspace.layout`）取 `animation/scenes/*.py`、`narrative/timing.json` 的音频路径 → 用 `ManimRenderEngine.render`（T1，全画质）逐镜头渲染 → 音频合成/字幕/拼接（迁移自 `../ai-video` 对应逻辑；如果旧项目里这部分和 manim.py 的 `render` 耦合在一起，直接复用 `RenderRequest.scenes[].audio`，不用另起字幕引擎——本计划字幕先做"按镜头旁白硬编码时间轴"，不引入新的字幕对齐算法）→ 写 `output/final.mp4` + `output/final.json`（记录 `snapshot_id`、镜头哈希、渲染时间）→ `complete`/`fail`。
  - 缓存键：`(scene_code_hash, audio_hash, quality, engine_version)` 的哈希，命中则跳过重渲染该镜头（design §5.3）；本任务先实现，缓存文件放 `data/projects/<id>/.render_cache/<hash>.mp4`（新建目录，落在工作区之外，或工作区内但不进快照——须核实 `workspace.layout` 是否已经定义了"不进快照"的目录约定，缺失则在决策记录里定为工作区旁的 `render_cache/` 兄弟目录，不受快照/越界检查约束）。
  - 心跳：渲染每个镜头前后调用 `heartbeat`；进度按"已完成镜头数/总镜头数"更新。
  - `scripts/dev.sh`：加一段 `(cd "$ROOT_DIR/backend" && exec "$UV" run python -m studio.worker) &`，`pids+=("$!")`，输出一行日志；worker 不需要 `--reload`（design：工作区不能被 reload 监听，worker 本身也不需要热重载，保持简单）。
  - 测试用的项目数据复用 T4 的 fixture（`seed_animation_project`），不重复构造一套叙事/音频数据。
- **测试**：`create_job(type="final_render")` 后跑一轮 worker 主循环单次迭代（不用真跑无限循环，函数拆成 `run_once(engine, ...) -> bool`），验证产出 `final.mp4`/`final.json`、`job.status == "done"`；渲染失败的镜头（故意写错的 scene 代码）验证 `job.status == "failed"` 且 `error` 有出错镜头信息；`reap_stale_running` 在 worker 启动时生效。
- **完成标准**：`pytest backend/tests/test_worker.py` 通过；`make dev` 起三个进程（api/worker/frontend），日志里能看到 worker 心跳/领取记录。
- **验证命令**：`make check`；`make dev` 手动确认三个进程都启动

### T6：`stages.common`——`suggest_upstream_change` 工具与 `suggestions` 仓储（待开始）

- **目标**：`suggestions` 表（M1 已建，`backend/src/studio/db/models.py:145` `Suggestion`）有仓储函数；`stages.common` 暴露一个可被任意阶段接入的 `ToolSpec`，调用后写入一条 `status="open"` 的建议。
- **涉及文件**：新建 `backend/src/studio/db/repo/suggestions.py`、`backend/src/studio/stages/common/suggest_upstream_change.py`（新建，`stages/common/__init__.py` 导出）、`backend/tests/db/test_repo_suggestions.py`（新建）、`backend/tests/stages/test_common.py`（新建）。
- **接口与要点**：
  - `repo/suggestions.py`：`create_suggestion(engine, *, project_id, from_stage, to_stage, content, turn_id) -> SuggestionValue`、`get_suggestion`/`list_suggestions(engine, project_id, status=None)`、`update_suggestion_status(engine, suggestion_id, status)`（`applied`/`dismissed`，M5 才会真正调用，本任务只要函数存在并有测试）。
  - `suggest_upstream_change` 的 `ToolSpec`：`input_model`（pydantic）字段 `to_stage: str`、`content: str`；`handler(ctx: ToolContext, args)`：`from_stage=ctx.stage`，写 `suggestions`，返回 `ToolResult(text="已记录回退建议，会在对话中提醒用户处理。")`；`stages={"animation"}`（先只给动画阶段用，M3 narrative 复用时把自己的名字加进 `stages` 集合，不用改这个文件的其它部分）。
- **测试**：调用工具后 `suggestions` 表新增记录，字段正确；`list_suggestions` 按 `status` 过滤；`update_suggestion_status` 生效。
- **完成标准**：`pytest backend/tests/db/test_repo_suggestions.py backend/tests/stages/test_common.py` 通过。
- **验证命令**：`make check`

### T7：`stages.animation`——`validate_scenes` 工具（待开始）

- **目标**：animation agent 能调用 `validate_scenes`，读取工作区 `animation/scenes/*.py`，用 T1 的引擎做静态校验，失败时报出具体镜头编号。
- **涉及文件**：`backend/src/studio/stages/animation/__init__.py`（`tools()` 补上这个 ToolSpec，读 `_WRITE_SCOPE` 已有的 `animation/scenes/**`）、新建 `backend/src/studio/stages/animation/validate_scenes.py`、`backend/tests/stages/test_animation_validate.py`（新建）。
- **接口与要点**：
  - 迁移 `../ai-video/backend/app/services/strategies/agent_sandbox.py` 里 `scene_filename`/`read_scene_codes`/`validate_workdir` 的思路，但改成直接从 `ctx.workdir` 读文件（不再需要旧项目那套"沙箱 workdir + input.json"，因为本项目的镜头元数据来自上游 `upstream/narrative/narrative.json`，不是单独维护的 `input.json`）。
  - `ToolSpec`：无入参（`input_model` 一个空 pydantic model），`stages={"animation"}`；`handler`：从 `ctx.workdir` 按 `upstream/narrative/narrative.json` 里的 `scenes[].id` 顺序读 `animation/scenes/<scene_id>.py`（读取上游只读副本用 `workspace.upstream` 现有能力，本任务只消费，不改 `workspace`），缺失/为空的镜头直接报错（不进引擎），其余交给 `ManimRenderEngine.validate_code`；失败时 `ToolResult(text=..., is_error=True)`，文本里点名具体 `scene_id`。
  - `narrative.json` 的读取需要一个轻量 schema（本任务只取 `scenes[].id`，不需要 T4 fixture 之外定义完整的 pydantic schema——完整 schema 属于 M3 的 `stages.narrative` 产物 schema，这里用 `dict`/`TypedDict` 读取即可，避免跨阶段耦合出一个"提前于 M3 的" schema 模块）。
- **测试**：使用 T4 的 fixture 项目；全部镜头都合法 → 工具返回通过；某镜头文件缺失 → 报错并点名；某镜头代码有语法错误 → 报错并点名（复用 T1 的 traceback 定位能力）。
- **完成标准**：`pytest backend/tests/stages/test_animation_validate.py` 通过。
- **验证命令**：`make check`

### T8：`stages.animation`——`render_preview(scene_id)` 工具（待开始）

- **目标**：animation agent 能调用 `render_preview(scene_id)`，拿到关键帧图片（`ToolResult.images`）和文本指标（渲染/配音时长偏差），120 秒超时返回工具错误而不是挂起整轮。
- **涉及文件**：`backend/src/studio/stages/animation/__init__.py`（`tools()` 加这个 ToolSpec）、新建 `backend/src/studio/stages/animation/render_preview.py`、`backend/tests/stages/test_animation_preview.py`（新建）。
- **接口与要点**：
  - `input_model` 字段：`scene_id: str`。
  - `handler`：从 `upstream/narrative/narrative.json`（镜头顺序、beat 数）和 `upstream/narrative/timing.json`（各镜头音频路径、时长、beat 起止时间）拼出 T2 的 `PreviewRequest`（`scenes` = `scene_id` 之前（含）所有镜头的 `SceneInput`，代码从 `animation/scenes/<id>.py` 读，音频从 `upstream/narrative/` 下 `timing.json` 指向的路径读）；调用 `ManimRenderEngine.render_preview`；把 `PreviewResult.keyframes` 转成 `studio.agent.events.ImageData`（PNG）放进 `ToolResult.images`，把渲染/配音时长和偏差拼成文本说明放进 `ToolResult.text`。
  - 图片是否真的发给模型由已有的 `supports_vision` 机制处理（`backend/src/studio/agent/openai_tools.py:81-104` 已经在 `supports_vision=False` 时剥掉图片只留文本，Claude 侧同理），本工具不用关心模型是否支持视觉。
  - `scene_id` 不存在于上游 `narrative.json` → 参数错误，`ToolResult(is_error=True)`。
- **测试**：使用 T4 的两镜头 fixture，对第二个镜头调用工具，验证返回的 `images` 数量等于该镜头 beat 数，文本里包含时长偏差；`scene_id` 不存在时报错；引擎超时时工具返回 `is_error=True` 且文本提示"预览渲染超时"。
- **完成标准**：`pytest backend/tests/stages/test_animation_preview.py` 通过。
- **验证命令**：`make check`

### T9：`stages.animation`——系统提示词完善（待开始）

- **目标**：`stages/animation/prompt.md` 从 M1 占位提示词，补齐代码规则、风格组件写法、manim 引擎约束、镜头合并约定，agent 能据此写出不重叠、可校验通过的镜头代码。
- **涉及文件**：`backend/src/studio/stages/animation/prompt.md`（改写）、新建 `backend/src/studio/stages/animation/rules.py`（迁移 `../ai-video/backend/app/codegen_rules.py` 的 `ELEMENT_EXIT_RULES`）、`backend/tests/stages/test_animation_prompt.py`（新建，轻量：断言提示词包含关键章节标题，不做语义测试）。
- **接口与要点**：
  - 提示词内容来源：`ELEMENT_EXIT_RULES`（画面不重叠规则，`rules.py`）、`../ai-video/backend/app/engines/ai/engine_specs/manim.yaml`（引擎约束/画幅规则，237 行，摘取和 manim 代码契约、API 版本相关的部分）、"各镜头代码合并到同一个 Scene 类"的约定说明、`validate_scenes`/`render_preview` 工具的使用时机（写完必须 `validate_scenes`，怀疑视觉问题时用 `render_preview` 自检）。
  - `prompt.md` 是纯文本，`system_prompt()` 方法已存在（`stages/animation/__init__.py`），本任务不改代码只改文案 + 补 `rules.py`。本任务排在 T7/T8 之后，因为提示词要点名这两个工具的用法，工具接口先定下来再写文案更不容易漂移。
- **测试**：提示词包含"画面不重叠"、"validate_scenes"、"render_preview"、"Scene 类"等关键词（粗粒度断言，避免过度测试文案）。
- **完成标准**：`pytest backend/tests/stages/test_animation_prompt.py` 通过；人工通读一遍提示词，确认和设计 §5.3、§8（风格组件经验）一致。
- **验证命令**：`make check`

### T10：api——渲染成片与任务查询/下载端点（待开始）

- **目标**：前端能创建 `final_render` 任务、轮询进度、下载/预览 `final.mp4`。
- **涉及文件**：新建 `backend/src/studio/api/jobs.py`（路由）、`backend/src/studio/api/schemas.py`（加 `JobOut` 等）、`backend/src/studio/main.py`（挂载路由）、`backend/tests/api/test_jobs.py`（新建）。
- **接口与要点**：
  - `POST /api/projects/{project_id}/render`：动画阶段必须先 `validate_scenes` 通过（或者不在 api 层强制，交给前端按钮禁用状态处理——决定权记入决策记录 D4：api 层只检查阶段状态不是 `locked`，不重复跑校验，避免和 agent 工具的校验逻辑产生两份实现）；调用 `jobs.repo.create_job(type="final_render", payload={"project_id":..., "snapshot_id": 当前工作区快照})`，返回 `JobOut`。
  - `GET /api/projects/{project_id}/jobs/{job_id}`：查询状态/进度/错误（前端每秒轮询，design §7 已定）。
  - `GET /api/projects/{project_id}/output/final.mp4`：任务 `done` 后从 `data/projects/<id>/output/final.mp4` 走 `FileResponse` 返回（复用 `api/files.py` 里现成的按路径读工作区文件的模式，若有）。
  - schema 命名和现有 `api/schemas.py` 风格对齐（`snake_case` 字段、`Out` 后缀）。
- **测试**：创建任务后能查到 `queued`；伪造一个 `done` 状态的 job 并放好 `output/final.mp4`，下载端点返回 200 和正确的 `Content-Type`；未定稿的动画阶段（`locked`）创建任务应返回 4xx。
- **完成标准**：`pytest backend/tests/api/test_jobs.py` 通过。
- **验证命令**：`make check`

### T11：api——成片定稿端点（待开始）

- **目标**：用户能"成片定稿"：校验 `final.json` 记录的快照等于当前最新快照后，把动画阶段标记 `finalized`，项目标记完成。
- **涉及文件**：`backend/src/studio/api/jobs.py` 或新建 `backend/src/studio/api/animation.py`（视 T10 路由体量决定拆分与否，决策记录 D5 写清楚放哪）、`backend/src/studio/db/repo/projects.py`（如果"项目标记完成"需要新字段，先确认 `Project` 表是否已有 `completed_at`/`status` 之类字段，没有就走 Alembic 新迁移）、`backend/tests/api/test_animation_finalize.py`（新建）。
- **接口与要点**：
  - `POST /api/projects/{project_id}/animation/finalize-render`：读 `output/final.json` 的 `snapshot_id`，和 `snapshots` 表当前最新快照比较，不一致则 4xx（提示"工作区有未纳入成片的改动，请重新渲染"）；一致则调用 `stage_flow.finalize(..., "animation")`，并把项目标记完成（若 `Project` 无此字段，本任务新增一个 Alembic 迁移，字段和取值记入决策记录）。
- **测试**：`final.json` 快照落后于当前工作区 → 4xx；一致 → 阶段变 `finalized`，项目标记完成。
- **完成标准**：`pytest backend/tests/api/test_animation_finalize.py` 通过。
- **验证命令**：`make check`

### T12：前端——动画画布：镜头列表与预览（待开始）

- **目标**：`features/canvas/animation/` 提供镜头列表（状态：已渲染/已过期/校验失败）、代码编辑器（复用 `CodeEditor.vue`）、预览关键帧条。
- **涉及文件**：新建 `frontend/src/features/canvas/animation/AnimationCanvas.vue`、`SceneList.vue`、`KeyframeStrip.vue`，配套 `.spec.ts`（纯逻辑部分，仿 `features/canvas/generic/` 的 `fileKind.ts` 风格拆出 `.ts` 单测）；`frontend/src/types/`（加动画阶段相关类型）；`frontend/src/pages/ProjectWorkbenchPage.vue` 或阶段路由处接入。
- **接口与要点**：
  - 复用 T10 之前已有的通用文件树/编辑器组件读写 `animation/scenes/*.py`（不重新发明文件读写，`features/canvas/generic/FileCanvas.vue` 的模式可以参考甚至部分复用）。
  - 镜头状态来自：`upstream/narrative/narrative.json` 的镜头列表 + 对应 `animation/scenes/<id>.py` 是否存在/最近一次 `validate_scenes`（M2 先不做"最近校验结果"的持久化展示，若无处可查，状态先简化为"文件存在/不存在"，完整的"已校验/已过期"状态跟踪记入决策记录，作为技术债还是本任务范围，执行时判断并记录）。
  - 关键帧展示：调用工具产生的图片走对话事件流（`agent/events.py` 的 `ImageData` 已经会作为工具结果事件落库并通过 SSE 推送），前端画布是否需要单独"重新拉取关键帧"的按钮，还是只在对话里看，执行时按现有 SSE 事件流是否已经够用来判断，避免重复造一条 HTTP 端点。
- **测试**：`.spec.ts` 覆盖镜头状态计算的纯函数；组件层面靠 `make dev` 手动走查（`docs/runbooks/verification.md` 的前端验收约定）。
- **完成标准**：`make dev` 手动打开动画阶段，能看到镜头列表、编辑代码、在对话里触发 `render_preview` 后看到关键帧图片出现在对话流。
- **验证命令**：`pnpm --dir frontend test`；`make dev` 手动走查（截图记入「验证记录」）

### T13：前端——成片面板（待开始）

- **目标**：成片面板：渲染成片按钮、任务进度条（轮询 T10 的查询端点）、播放器（`output/final.mp4`）、成片定稿按钮（调 T11）。
- **涉及文件**：新建 `frontend/src/features/canvas/animation/FinalRenderPanel.vue`、`frontend/src/composables/`（加一个任务轮询的 composable，仿现有 TanStack Query hooks 风格）、配套 `.spec.ts`。
- **接口与要点**：
  - 轮询间隔和现有 `jobs` 表设计一致（design §7"worker 的任务进度由 api 每秒轮询一次 jobs 表"是 api↔worker 之间的轮询；前端↔api 的轮询间隔本任务自己定，1 秒起步，`done`/`failed` 后停止轮询）。
  - 渲染成片按钮的禁用条件（例如上一次校验未通过时禁用）在决策记录里写清楚判断依据，避免和 T10 的 api 层校验产生不一致的两套规则。
- **测试**：`.spec.ts` 覆盖轮询状态机（`queued → running → done/failed` 时组件展示什么、何时停止轮询）；手动走查播放器能播放 `final.mp4`。
- **完成标准**：`make dev` 手动走查：点击渲染成片 → 看到进度变化 → 完成后能播放 → 点击成片定稿后阶段状态变化。
- **验证命令**：`pnpm --dir frontend test`；`make dev` 手动走查

### T14：集成验证与风险验证（待开始）

- **目标**：端到端跑通 T4 fixture 项目：叙事定稿 → animation agent（`FakeRuntime`）一轮 → `validate_scenes` → `render_preview` → 创建 `final_render` 任务 → worker 产出成片 → 成片定稿；补一条渲染集成测试（设计 §8"渲染集成测试"）。
- **涉及文件**：新建 `backend/tests/api/test_animation_flow.py`（端到端，标记慢测试）、`backend/tests/engines/test_manim_engine.py` 里补一条"渲染一个极小 manim 镜头并抽取关键帧"的集成用例（如果 T1/T2 的单测已经覆盖，这里改成引用说明，不重复）。
- **接口与要点**：
  - 这条测试串联 T1–T11 的产物，是本计划的"验收标准 AC4"证据来源。
  - 顺带确认设计 §9 风险表里和渲染相关的项（R1–R5 是 M1 范围，已完成；本计划若发现新的风险假设不成立，按 SOP §6 升级条件处理，不在这里私自改设计）。
- **测试**：见上。
- **完成标准**：`pytest backend/tests/api/test_animation_flow.py`（慢测试单独跑）通过；`make check` 全绿。
- **验证命令**：`make check`；`pytest backend/tests -m slow`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-09-28 — T1：`engines.render` 协议与 manim 引擎迁移 — 完成。`engines/render/{base,format}.py` + `engines/render/manim/{script,process,engine}.py`（决策记录 D1 的拆分）；`backend/tests/engines/test_manim_engine.py` 迁移全部静态分析用例并新增一条端到端 mp4 渲染用例（AC1）；新增 `slow` pytest marker 与 `manim`/`pyflakes` 依赖；新增 import-linter 契约"engines 是纯能力层"；pyright 全绿（`EngineRegistry` 加了 `RenderEngine` 上界、修了几处 possibly-unbound/None 缩窄）。`make check` 全绿（见本提交）。
- 2026-09-28 — T2：`engines.render` 预览渲染与关键帧抽取 — 完成。新建 `engines/render/manim/keyframes.py`（`extract_keyframe`/`probe_duration_seconds`，ffmpeg/ffprobe 子进程）；`ManimRenderEngine.render_preview` 实现：低清（480×270/15fps）渲染 → 按 `beat_end_times` + 起始偏移抽关键帧 → 有 `audio_duration_seconds` 时算时长偏差；超时走 `run_render` 自身的 `timeout_seconds`（可传参，测试用极小值触发，不用真等 120 秒），映射成"预览渲染超时"。过程中发现 manim `add_sound()` 的音轨最短 1 秒的坑（决策记录 D10，同时写进 `docs/references/manim.md`）。`backend/tests/engines/test_manim_preview.py` 4 个用例（AC2）。`make check` 全绿（见本提交）。
- 2026-09-28 — T3：`jobs` 模块——SQLite 任务队列 — 完成。`create_job`/`claim_next`/`heartbeat`/`update_progress`/`complete`/`fail`/`get_job`/`list_jobs`/`reap_stale_running`；实际的 `Job` 模型读写按 ARCHITECTURE 规则 5 落在新建的 `db/repo/jobs.py`，`jobs/repo.py` 只转发（决策记录 D11），公共接口仍是计划里写的 `studio.jobs.*`。新增两条 import-linter 契约（"jobs 不直接依赖 db.models"、"jobs 不依赖 main"）。`backend/tests/jobs/test_repo.py` 7 个用例（AC3），`reap_stale_running` 用直接改写 `heartbeat_at` 而不是等待真实超时来区分"过期"和"新鲜"两条任务。`make check` 全绿（见本提交）。
- 2026-09-28 — T4：手工叙事 fixture 与开发种子脚本 — 完成。新建 `backend/tests/fixtures/animation/{narrative.json,timing.json,seed.py,generate_audio.py,audio/{s-hook,s-explain}.wav}`：`narrative.json` 两个镜头（`s-hook`/`s-explain`，各 2 个 beat，字段齐全）；`timing.json` 对应的 `audio_hash`（真实 sha256，脚本打印后手动填入）、`duration_seconds`（1.4s/1.6s，均 ≥ 1.0s，避开 `docs/references/manim.md` 记录的 1 秒静音底轨坑）、beat 起止时间、简化的逐字时间戳、`alignment_coverage=1.0`；`audio/*.wav` 由 `generate_audio.py`（标准库 `wave`/`math`，带淡入淡出的正弦波，不依赖外部 API）生成并提交产物+脚本。`seed.py` 的 `seed_animation_project(engine, blobs, *, data_dir) -> project_id`：建项目 → 定稿 topic（解锁 narrative）→ 写入 fixture 到 `narrative/` → 定稿 narrative（解锁 animation）。测试先红后绿：`backend/tests/test_animation_fixture.py` 4 个用例（`seed_animation_project` 直接调用 3 个 + 新增的 `animation_project` pytest fixture 1 个），断言 animation 阶段变 `active`、`upstream/narrative/` 物化后能读到 fixture 内容、两次调用互相独立。`animation_project` fixture 加进顶层 `backend/tests/conftest.py`（决策记录 D13）。顺手修正 `docs/references/manim.md` 里两处过期的任务编号（"T9 fixture"/"T4/T5" → 现在的 T4/T5）。`make check` 全绿（631 passed / 14 deselected，前端 128 passed，import-linter 18 kept，pyright 0 errors）。
- 2026-09-28 — T5：`worker` 进程与 `make dev` 接入 — 完成。新建 `backend/src/studio/worker.py`：`run_once`（单次迭代，方便测试）→ reap 过期心跳 → `claim_next(type="final_render")` → 读工作区顶层 `narrative/narrative.json`+`timing.json`（决策记录 D15，不经 `upstream/`）和每个镜头的 `animation/scenes/<id>.py` → 逐镜头单独渲染（决策记录 D16）+ 缓存（决策记录 D14）→ 拼接（ffmpeg concat demuxer，流复制）→ 按镜头旁白叠加字幕（决策记录 D17，Pillow 画字幕图 + ffmpeg `overlay`）→ 写 `output/final.mp4`+`output/final.json`（决策记录 D20）→ `complete`/`fail`。`scripts/dev.sh` 加了 worker 进程（去掉"worker 留到 M2"注释）；`AGENTS.md`「常用命令」同步。`backend/pyproject.toml` 新增 3 条 import-linter 契约（worker 是组装层、不直接依赖 db.models、只依赖 jobs/engines/workspace/db/config）+ `pillow` 直接依赖（决策记录 D17）。`backend/tests/test_worker.py` 8 个用例（5 个快、3 个慢：空队列/reap/镜头代码缺失/缓存键/缓存命中跳过重渲染 是快测试；端到端产出 final.mp4+json、缓存跨任务复用、坏代码点名出错镜头 是慢测试）。手动用真实 `make dev` 验证：三个进程都起来，往运行中的 sqlite 库直接插入一条 `final_render` 任务后，日志里能看到 `[worker] 领取任务`/`[worker] 镜头 ... 渲染完成`/`[worker] 任务 ... 完成`；额外抽帧核对过成片画面确实叠了正确的字幕文字（见「验证记录」）。`make check` 全绿（见本提交）。

## 下一步

- 从 T6 开始：`stages.common`——`suggest_upstream_change` 工具与 `suggestions` 仓储。
  - 新建 `backend/src/studio/db/repo/suggestions.py`（和 `db/repo/jobs.py`/`snapshots.py` 同一种写法：只读值对象 `SuggestionValue` + 普通函数，不泄露 ORM 对象，`Suggestion` 模型定义在 `backend/src/studio/db/models.py:145`）：
    - `create_suggestion(engine, *, project_id, from_stage, to_stage, content, turn_id) -> SuggestionValue`：初始 `status="open"`。
    - `get_suggestion(engine, suggestion_id) -> SuggestionValue | None`、`list_suggestions(engine, project_id, status=None) -> list[SuggestionValue]`（`status` 传了就过滤，不传返回全部）。
    - `update_suggestion_status(engine, suggestion_id, status) -> SuggestionValue`（`status` 传 `"applied"`/`"dismissed"`；M5 才会真正被调用，这里只要函数存在、行为正确、有测试）。
  - 新建 `backend/src/studio/stages/common/suggest_upstream_change.py`，`stages/common/__init__.py` 导出（M1 起这个包一直是空的，现在补上第一个真正的共用工具）：
    - `input_model`（pydantic `BaseModel`）：`to_stage: str`、`content: str`。
    - `handler(ctx: ToolContext, args) -> ToolResult`：`from_stage=ctx.stage`（`ToolContext` 已有这个字段，见 `backend/src/studio/agent/tools.py`），调 `create_suggestion(...)` 写一条记录，返回 `ToolResult(text="已记录回退建议，会在对话中提醒用户处理。")`。
    - `ToolSpec(name=..., description=..., input_model=..., stages={"animation"}, handler=...)`——先只给动画阶段用；M3 的 narrative agent 要复用时只需要把 `"narrative"` 加进这个 `stages` 集合，不用改文件其它部分（`ToolSpec.stages` 就是"哪些阶段可以用这个工具"的声明，见 `agent/tools.py` 的 `ToolSpec` 定义）。
  - **执行时需要判断、不用回来问的点**：T6 的"涉及文件"列表里没有 `backend/src/studio/stages/animation/__init__.py`——现在 `AnimationStage.tools()` 还是硬编码 `return []`（M1 占位）。判断一下 T6 本身要不要顺手把 `suggest_upstream_change` 接进 `AnimationStage.tools()`（这样这个工具才能真的被 agent 调用到，不只是被单元测试直接调），还是这条线留给 T7/T8/T9 一起接（那两个任务本来就要改 `animation/__init__.py` 的 `tools()`）。判断依据：AC5 的验证命令只是 `pytest backend/tests/db/test_repo_suggestions.py backend/tests/stages/test_common.py`（直接 `invoke_tool` 调用，不经过 `AnimationStage.tools()`），照此看 T6 本身不强制要求接线；但如果不接，"动画阶段的 `suggest_upstream_change` 工具"这句 AC5 原文在人工走查时会显得名不副实。两种做法都合理，选一种、记进决策记录说明理由即可。
  - 测试：新建 `backend/tests/db/test_repo_suggestions.py`（`create_suggestion` 建记录字段正确；`list_suggestions` 按 `status` 过滤；`update_suggestion_status` 生效，仿 `backend/tests/jobs/test_repo.py` 的写法和 fixture 风格）；新建 `backend/tests/stages/test_common.py`（直接构造一个 `ToolContext` 调 `invoke_tool`，断言 `suggestions` 表新增一条 `status="open"` 的记录，字段和调用参数对得上；这两个测试都不需要真实渲染，不用标 `slow`）。
  - 完成标准：`pytest backend/tests/db/test_repo_suggestions.py backend/tests/stages/test_common.py` 通过（AC5）。
  - 验证命令：`make check`。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-09-28 — D1：manim 引擎迁移时从单文件（836 行）拆成 `engines/render/manim/{script,process,engine}.py` 包 — 原文件已经较大，T2 还要再加 `render_preview` 相关逻辑，按职责先拆开比继续堆大文件更利于后续维护；不改变对外接口（仍是一个 `ManimRenderEngine`）。
- 2026-09-28 — D2：`jobs.claim_next` 只保证同进程内不重复领取，不做跨进程分布式锁 — 设计明确 M2 只跑单个 worker 进程（design §10"worker 成片"、AGENTS.md 命令表"worker 在 M2 加入"未提多副本），过度设计成本不划算，真要多 worker 时再补。
- 2026-09-28 — D3：手工叙事 fixture 的音频用脚本生成的静音/正弦波 wav，不用真实 TTS 或人工录音 — TTS 引擎明确是 M3 范围（`docs/references/legacy-assets.md` 第 14 行），M2 的"手工准备叙事 fixture"不应该提前依赖 M3 能力或引入外部录音资产。
- 2026-09-28 — D4：`POST /api/.../render` 只检查动画阶段状态不是 `locked`，不在 api 层重复跑 `validate_scenes` 的校验逻辑 — 避免同一份校验规则在 agent 工具和 api 层出现两份实现、容易漂移；未校验直接渲染的后果由 worker 渲染失败时的错误信息兜底（design §6"成片任务失败"行）。
- 2026-09-28 — 计划制定时确认：`preamble.py` 的"按镜头 id 摘要上游变更"（design §5.4）留给 M3（`gather_preamble_inputs` 现有实现已经在文档注释里写明"M1 不做按镜头 id 的摘要"），本计划不升级这部分，见「范围·不包含」。
- 2026-09-28 — D6：批准前复核依赖顺序，发现手工叙事 fixture（原 T9）在原排序中排在 worker（原 T4）、`validate_scenes`（原 T6）、`render_preview`（原 T7）之后，但这三个任务的测试都要读这个 fixture 项目才能写——顺序早于依赖会导致执行到那几步时没有可用的测试数据。调整为：fixture 提到 T3 之后、其余动画阶段任务之前，原 T4/T5/T6/T7/T8 依次后移为 T5/T6/T7/T8/T9（T1/T2/T3/T10–T14 编号不变，因为它们互相之间或对 fixture 没有这层前置关系）。已同步更新任务正文里的交叉引用（T14 的"T9 fixture"改为"T4 fixture"、fixture 任务的"完成标准"消费者列表改为 T5/T7/T8）。
- 2026-09-28 — D7（T1）：`RenderEngine` 协议新增 `render_preview` 方法签名需要 `PreviewRequest`/`PreviewResult`/`PreviewKeyframe` 这三个类型存在，但计划原文把它们的定义写在 T2。为避免 T1 里出现"签名引用不存在的类型"，直接把这三个 dataclass 按 T2 计划里写的字段原样加进 T1 的 `base.py`，`ManimRenderEngine.render_preview` 本体在 T1 只是 `raise NotImplementedError`。T2 不用再重复定义这几个类型，只需要实现方法体和 `keyframes.py`。
- 2026-09-28 — D8（T1）：新增 `slow` pytest marker，`addopts` 改成 `-m 'not smoke and not slow'`——凡是会起 manim 子进程（dry-run 校验或全画质渲染）的测试都标 `@pytest.mark.slow`，默认 `make check` 跑的 `pytest` 会把它们跳过（deselected，不是失败），需要时用 `pytest ... -m slow` 单独跑；纯字符串拼装/AST 变换的测试（`_build_manim_script`/`_prepare_manim_code` 等）不标，仍在默认范围内。T1 自验证时两组都手动跑过一遍，见「验证记录」。
- 2026-09-28 — D9（T1）：`pyright` 是 studio 项目的机器检查（legacy 项目没有），迁移代码时补了几处类型收紧，不改变行为：`EngineRegistry[T]` 加上界 `T: RenderEngine`；`process.py` 里 `proc.stdout`（PIPE 模式下运行时保证非 None）加了 `assert`；`script.py` 的签名校验里 `**{kw.arg: None for kw in node.keywords}` 改成过滤掉 `kw.arg is None` 的项（上面已有等价的运行时 guard，这里只是让 pyright 也能看见）；`_build_manim_script` 里 `duration` 提前初始化为 `0.0`，避免 pyright 认为它在第二个 `if include_audio:` 块里"可能未绑定"。
- 2026-09-28 — D10（T2）：`extract_keyframe` 的 ffprobe 探测总时长要用 `-select_streams v:0`（视频流）而不是 `format=duration`（容器整体）——manim 的 `add_sound()` 会给音轨套一层至少 1 秒的静音底轨（见「意外与发现」和 `docs/references/manim.md`），容器时长会被音轨拖长，用它算"目标镜头的实际渲染时长"会系统性偏大。抽帧时的安全上限也要留整整一帧（`1/fps`）而不是半帧：ffmpeg 的 `-frames:v 1` 找的是"第一个 PTS ≥ 目标时刻"的帧，最后一帧的 PTS 是 `(nb_frames-1)/fps`，比视频时长（`nb_frames/fps`）少一帧，留少了会抽不到东西。`extract_keyframe` 的 `-ss` 放在 `-i` 之后（解码寻址而非快速寻址）：预览视频很短，快速寻址靠关键帧索引经常直接跳过内容，短视频里解码开销可以忽略。
- 2026-09-28 — D11（T3）：计划里 T3 写的文件路径是 `backend/src/studio/jobs/repo.py`，但 `Job` ORM 模型的直接读写按 ARCHITECTURE 规则 5（"只有 `db` 定义 ORM 模型；其他模块只通过 `db.repo` 读写"）不该放在 `studio.jobs` 包里——`workspace`/`agent`/`stages`/`api` 都有一条"不直接依赖 `db.models`"的 import-linter 契约，`jobs` 不应该是例外。把实现挪到新建的 `studio/db/repo/jobs.py`（和 `projects.py`/`stages.py`/`snapshots.py` 同级），`studio/jobs/repo.py` 改成纯转发（`from studio.db.repo.jobs import ...`），`studio.jobs` 对外的公共接口（函数名、`JobValue`）和计划里写的完全一样，只是实现的物理位置变了。
- 2026-09-28 — D12（T4）：`seed_animation_project` 内部自建一个只含 `topic`/`narrative`/`animation` 三个占位阶段的 `StageRegistry`，不改变计划原文写的对外签名（`seed_animation_project(engine, blobs, *, data_dir) -> project_id`，没有 `registry` 参数）——`stage_flow.finalize` 需要 `registry` 才能算出下游阶段该不该解锁，但这三个阶段是 `studio.stages.{topic,narrative,animation}` 导出的模块级单例（`STAGE`），和 `main.create_app`/`agent/conftest.py` 组装出的 registry 里注册的是同一批对象；在 `seed.py` 内部再注册一次不产生"两份定义"，也不需要调用方额外传参。
- 2026-09-28 — D13（T4）：`animation_project` pytest fixture 放进顶层 `backend/tests/conftest.py`，不放 `backend/tests/api/conftest.py`——pytest fixture 按 conftest 所在目录的子树生效；这个 fixture 未来的消费者（T5 的 `tests/test_worker.py`、T7/T8 的 `tests/stages/test_animation_*.py`、T14 的 `tests/api/test_animation_flow.py`）分布在好几个互不相邻的目录，放在 `tests/api/` 下只有 `api/` 子树能用，放在顶层才能让所有子目录共用同一份 fixture，不用各自重新构造种子数据。种子逻辑本身（`seed_animation_project`）仍然独立测试（`backend/tests/test_animation_fixture.py`），`animation_project` 只是薄薄一层 pytest 包装。
- 2026-09-28 — D14（T5）：渲染缓存放 `data/projects/<id>/.cache/render_cache/<hash>.mp4`，不新起顶层目录 —— `workspace.layout.EXCLUDED_TOP_DIRS` 已经把 `.cache/` 定义为"不参与快照、对 agent/前端隐藏"的目录（T1/T4 之前就有），渲染缓存正好符合这个语义（工作区内、但不是"工作区内容"），复用现成约定比新起一个 `.render_cache/` 兄弟目录并另外教会 `workspace`/`scope.guard` 认识它成本更低，也不用改 `EXCLUDED_TOP_DIRS`。
- 2026-09-28 — D15（T5）：worker 读叙事产物直接读工作区顶层的 `narrative/narrative.json`/`timing.json`，不走 `upstream/` 物化 —— 两个理由：(1) ARCHITECTURE §2 依赖表把 `worker` 限定为只能依赖 `jobs`/`engines`/`workspace`/`db`/`config`，不能依赖 `agent`，而 `upstream_sources`/`materialize_upstream` 那套机制的"哪些阶段该物化"由 `agent.stage_flow`+`agent.stage.StageRegistry` 决定，worker 用不了（也已经用一条新增的 import-linter 契约把这条边界钉死，不是只停留在文档约定）；(2) `upstream/` 本来就只是"给 agent 轮次内的原生文件工具用的只读副本"，narrative 阶段定稿后的真实产物一直留在工作区顶层 `narrative/`，不需要经过物化就能直接读到，物化是 downstream 的便利机制而不是数据的唯一来源。
- 2026-09-28 — D16（T5）：worker 逐镜头单独调用 `ManimRenderEngine.render`（每次 `RenderRequest.scenes` 只有一个元素），不是像 T2 的 `render_preview`/旧项目那样把所有镜头拼成一个请求一次性渲染 —— 计划要求的缓存键 `(scene_code_hash, audio_hash, quality, engine_version)` 是"每个镜头"粒度的，只有单独渲染才能做到"改一个镜头只重渲一个镜头"；副作用（manim 音轨 1 秒静音下限变成按镜头单独触发，而不是像 T2 那样看总时长）记进了 `docs/references/manim.md`。拼接用 ffmpeg concat demuxer 流复制（不重新编码），字幕叠加时用 ffprobe 实测的各镜头片段时长（不是 timing.json 声明的时长）算时间轴偏移，避免这个副作用影响字幕对齐。
- 2026-09-28 — D17（T5）：字幕不走 ffmpeg 的 `drawtext`/`subtitles` 滤镜，改用 Pillow 画字幕 PNG + ffmpeg `overlay` 滤镜按时间窗口叠加 —— 实测本机 Homebrew 安装的 ffmpeg（8.0.1）编译时没有启用 libass/libfreetype，`ffmpeg -filters` 找不到这两个滤镜（见 `docs/references/ffmpeg.md`），装 libass 重新编译 ffmpeg 是计划外的系统环境改动，改用已经在依赖图里的 Pillow（`manim` 自己声明依赖 `pillow>=11.0`，backend `pyproject.toml` 这次把它列成自己的直接依赖，不是引入新包）风险更小、不用碰系统 ffmpeg。字幕文本取"镜头完整旁白"，显示区间硬编码为该镜头在成片里的起止时间（符合计划范围"不引入新的字幕对齐算法"），不做逐 beat/逐词对齐；`beats[].cue_text`/`word_timestamps` 留给以后如果要做更细粒度字幕时用。
- 2026-09-28 — D18（T5）：字幕用的中文字体从一份写死的候选路径列表里按存在与否选第一个（macOS 系统自带的 STHeiti/PingFang/Songti，外加几个常见 Linux Noto CJK 路径），不引入字体文件资产或额外的字体渲染依赖 —— 项目是单人本地使用（AGENTS.md），manim 本身渲染中文公式也依赖本机已装的 xelatex/ctex（见 `docs/references/manim.md`），这里延续同样的"假设本机环境已具备"策略；候选列表找不到任何一个时 worker 会明确报错点名"找不到可用的中文字体"，不会静默产出没有字幕的成片。
- 2026-09-28 — D19（T5）：`run_once` 每次调用都执行一次 `reap_stale_running`，不是只在 worker 进程刚启动时执行一次 —— 单 worker 进程同一时刻最多一个 `running` 任务（D2），重复 reap 只是一次幂等的空查询，比单独维护"本进程是否已经在启动时 reap 过"的状态更简单；这样 `run_once` 自身就是一个完整、可独立测试的单元，测试 reap 行为不需要额外模拟"进程刚启动"这层语境。
- 2026-09-28 — D20（T5）：`output/final.json` 里的 `snapshot_id`，取自 worker 在读到镜头代码/音频后立刻显式调用的 `create_snapshot(..., reason="final_render")`（内容未变时直接返回已有快照，不产生冗余记录），而不是读取当时已经存在的"最新快照" —— 保证记录的快照精确对应本次渲染实际读到的内容，不受"工作区有尚未被任何快照捕获的改动"这类边界情况影响；T11（成片定稿）要用这个字段和当前最新快照比较，这个不变量必须成立。
- 2026-09-28 — D21（T5）：worker 用 `JobValue.project_id`（`jobs` 表的顶层非空列，`create_job` 强制要求传入）确定要渲染哪个项目，不从 `payload` 字典里取 —— `payload` 留给以后（T10）可能需要的额外信息（例如创建任务时的快照 id），T5 本身用不到，也避免"project_id 在 payload 里缺失"这种结构上不可能出现的情况需要额外处理。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 2026-09-28（T2）：manim 的 `Scene.add_sound()` 会给整段视频的音轨套一层至少 1 秒的静音底轨（`pydub.AudioSegment.silent()` 不传参时默认 1000ms），即使所有镜头声明的音频时长加起来远小于 1 秒，容器时长也会被这条底轨拖到 ~1.0s+。单测里用的合成静音音频要 ≥ 1.0s 才不会踩到这个下限；真实叙事音频（旁白通常几秒）基本不会遇到。已写进 `docs/references/manim.md`（2026-09-28，实测）。
- 2026-09-28（T5）：本机 Homebrew 安装的 ffmpeg（8.0.1）编译时没有启用 libass/libfreetype，`drawtext`/`subtitles` 滤镜都不可用（`ffmpeg -filters` 输出里没有这两项），计划里"加字幕"最常见的两条实现路径都走不通。改用 Pillow 画字幕图 + `overlay` 滤镜叠加（决策记录 D17），已写进新建的 `docs/references/ffmpeg.md`（2026-09-28，实测）。
- 2026-09-28（T5）：D16 提到的副作用——worker 逐镜头单独渲染后，manim 音轨 1 秒静音下限（T2 已发现的行为）变成按每个镜头单独触发，不是像 T2 的 `render_preview` 那样看"目标镜头之前所有镜头的总时长"。M2 fixture 的两个镜头（1.4s/1.6s）都不低于 1 秒没有踩到，但这是"渲染出的镜头时长 = 声明的音频时长"这个不变量在 worker 场景下的新边界条件，已更新进 `docs/references/manim.md` 的"影响范围"一节（2026-09-28）。

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- AC1（2026-09-28，L2）：`pytest backend/tests/engines/test_manim_engine.py` → `18 passed, 5 deselected`（慢测试被 `slow` marker 跳过）；`pytest backend/tests/engines/test_manim_engine.py -m slow` → `5 passed`，其中 `test_render_produces_mp4_for_minimal_two_scene_script` 对两个极简镜头（`Dot()`/`Square()`，各配一段脚本生成的静音 wav）跑 `ManimRenderEngine.render`，断言 `success is True` 且拿到非空 `video_bytes`；`test_validate_code_attributes_runtime_error_to_originating_scene` 覆盖 traceback 定位回具体镜头号。`make check` 全绿（后端 619 passed / 11 deselected，前端 128 passed，import-linter 16 kept，pyright 0 errors）。
- AC2（2026-09-28，L2）：`pytest backend/tests/engines/test_manim_preview.py` → `1 passed, 3 deselected`（超时用例默认就跑，见下）；`pytest backend/tests/engines/test_manim_preview.py -m slow` → `3 passed`：两镜头 fixture（各 1.0s）对第二个镜头调 `render_preview`，`test_render_preview_returns_one_keyframe_per_beat` 断言关键帧数等于 beat 数（2 个）且每张图非空；`test_render_preview_computes_duration_deviation` 断言时长偏差在 0.3s 容忍范围内；`test_render_preview_skips_deviation_without_audio_duration` 断言不给 `audio_duration_seconds` 时偏差是 `None`。`test_render_preview_times_out_without_waiting_120_seconds`（不标 slow，靠 `timeout_seconds=0.001` 参数触发，不用真等 120 秒）断言 `success is False`、`error_message == "预览渲染超时"`。`pytest backend/tests/engines -m slow` → `8 passed`（T1+T2 一起跑）。`make check` 全绿（后端 620 passed / 14 deselected，前端 128 passed，import-linter 16 kept，pyright 0 errors）。
- AC3（2026-09-28，L2）：`pytest backend/tests/jobs/` → `7 passed`：`test_claim_next_claims_once_then_queue_is_empty` 断言同一条 `queued` 任务只能领到一次，第二次返回 `None`；`test_reap_stale_running_only_affects_expired_heartbeats` 建两条 `running` 任务，手动把其中一条的 `heartbeat_at` 改到 120 秒前，`reap_stale_running(heartbeat_timeout_seconds=60)` 后只有那条变 `failed`，另一条仍是 `running`。`make check` 全绿（后端 627 passed / 14 deselected，前端 128 passed，import-linter 18 kept，pyright 0 errors）。
- T5（2026-09-28，L2；不是独立 AC——AC4 是端到端标准，要等 T6–T11 串起来才能勾）：`pytest backend/tests/test_worker.py` → `5 passed, 3 deselected`（快测试：空队列返回 `False`、reap 过期心跳任务、镜头代码缺失时报错点名 `s-hook`、缓存键随代码/音频哈希变化、缓存命中时第二次调用不再触发渲染）；`pytest backend/tests/test_worker.py -m slow` → `3 passed`：`test_produces_final_mp4_and_json_and_marks_job_done` 断言用 T4 fixture 的两镜头项目跑一次 `run_once` 后产出 `output/final.mp4`（非空）+ `output/final.json`（含 `snapshot_id`/`scene_hashes`/`rendered_at`）、`job.status == "done"`；`test_reruns_use_render_cache` 断言两个镜头各自的缓存文件（`.cache/render_cache/<hash>.mp4`）在第二次创建任务并渲染后 `mtime` 不变（没有被重渲）；`test_fails_job_with_scene_id_when_one_scene_has_broken_code` 把 `s-explain` 的代码换成一个不存在的 manim 类，断言 `job.status == "failed"` 且 `error` 里包含 `"s-explain"`。额外做了一次不经过 pytest 的手动核对：直接调用 `run_once` 产出 `final.mp4` 后，用 `ffprobe` 确认视频/音频两条流都在（`h264`+`aac`），用 `ffmpeg -ss ... -frames:v 1` 在两个镜头各自的时间窗口内抽帧，肉眼确认字幕文字（"如果一个排序算法能在一秒内处理十亿条记录，你会好奇它到底做了什么。"/"答案是分而治之：把大问题拆成小问题，分别解决后再合并。"）正确叠加在对应镜头画面下方，且切换时机符合各镜头时长。`pytest backend/tests/engines -m slow` 回归跑了一遍（T1/T2 的慢测试，8 passed），确认没有被这次改动带崩。`make check` 全绿（后端 636 passed / 17 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- T5 `make dev`（2026-09-28）：`make dev` 起 api（uvicorn，`:8000`）、worker（`python -m studio.worker`）、frontend（vite，`:5173`）三个进程，日志里能看到 `[worker] 已启动，轮询间隔 2.0s`。往正在运行的 `data/studio.db` 里用 `seed_animation_project` 建一个项目、写两个极简镜头代码、`create_job(type="final_render", ...)`，几秒内日志出现 `[worker] 领取任务 <id>（项目 <project_id>）` → 每个镜头的 `[worker] 镜头 <id> 渲染完成（Ns）` → `[worker] 任务 <id> 完成`，满足 T5 完成标准里"日志里能看到 worker 心跳/领取记录"。验证完 `kill` 了 `make dev`、uvicorn（含 reload 子进程）、vite 三组进程，确认没有残留（`ps aux` 复核）。
