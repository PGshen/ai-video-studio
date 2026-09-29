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
- [x] AC4：手工 fixture 项目上，从"叙事已定稿"状态开始，animation agent（`FakeRuntime`）跑一轮，调用 `validate_scenes` 和 `render_preview` 都能拿到预期结果；点击"渲染成片"后 worker 产出 `output/final.mp4` + `output/final.json`，"成片定稿"后阶段状态变 `finalized` 且项目标记完成（验证：`pytest backend/tests/api/test_animation_flow.py`，慢测试单独跑）
- [x] AC5：`animation` 阶段的 `suggest_upstream_change` 工具调用后 `suggestions` 表新增一条 `status=open` 的记录（验证：`pytest backend/tests/stages/test_common.py`）
- [x] AC6：前端动画画布能显示镜头列表、代码编辑器、预览关键帧和渲染成片进度/播放器（验证：`make dev` 手动走查 + `pytest frontend`；截图见「验证记录」）
- [x] AC7：`make check` 全绿，包含新增的 import-linter 契约（`engines`/`jobs`/`worker` 层）

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

### T6：`stages.common`——`suggest_upstream_change` 工具与 `suggestions` 仓储（完成）

- **目标**：`suggestions` 表（M1 已建，`backend/src/studio/db/models.py:145` `Suggestion`）有仓储函数；`stages.common` 暴露一个可被任意阶段接入的 `ToolSpec`，调用后写入一条 `status="open"` 的建议。
- **涉及文件**：新建 `backend/src/studio/db/repo/suggestions.py`、`backend/src/studio/stages/common/suggest_upstream_change.py`（新建，`stages/common/__init__.py` 导出）、`backend/tests/db/test_repo_suggestions.py`（新建）、`backend/tests/stages/test_common.py`（新建）。
- **接口与要点**：
  - `repo/suggestions.py`：`create_suggestion(engine, *, project_id, from_stage, to_stage, content, turn_id) -> SuggestionValue`、`get_suggestion`/`list_suggestions(engine, project_id, status=None)`、`update_suggestion_status(engine, suggestion_id, status)`（`applied`/`dismissed`，M5 才会真正调用，本任务只要函数存在并有测试）。
  - `suggest_upstream_change` 的 `ToolSpec`：`input_model`（pydantic）字段 `to_stage: str`、`content: str`；`handler(ctx: ToolContext, args)`：`from_stage=ctx.stage`，写 `suggestions`，返回 `ToolResult(text="已记录回退建议，会在对话中提醒用户处理。")`；`stages={"animation"}`（先只给动画阶段用，M3 narrative 复用时把自己的名字加进 `stages` 集合，不用改这个文件的其它部分）。
- **测试**：调用工具后 `suggestions` 表新增记录，字段正确；`list_suggestions` 按 `status` 过滤；`update_suggestion_status` 生效。
- **完成标准**：`pytest backend/tests/db/test_repo_suggestions.py backend/tests/stages/test_common.py` 通过。
- **验证命令**：`make check`

### T7：`stages.animation`——`validate_scenes` 工具（完成）

- **目标**：animation agent 能调用 `validate_scenes`，读取工作区 `animation/scenes/*.py`，用 T1 的引擎做静态校验，失败时报出具体镜头编号。
- **涉及文件**：`backend/src/studio/stages/animation/__init__.py`（`tools()` 补上这个 ToolSpec，读 `_WRITE_SCOPE` 已有的 `animation/scenes/**`）、新建 `backend/src/studio/stages/animation/validate_scenes.py`、`backend/tests/stages/test_animation_validate.py`（新建）。
- **接口与要点**：
  - 迁移 `../ai-video/backend/app/services/strategies/agent_sandbox.py` 里 `scene_filename`/`read_scene_codes`/`validate_workdir` 的思路，但改成直接从 `ctx.workdir` 读文件（不再需要旧项目那套"沙箱 workdir + input.json"，因为本项目的镜头元数据来自上游 `upstream/narrative/narrative.json`，不是单独维护的 `input.json`）。
  - `ToolSpec`：无入参（`input_model` 一个空 pydantic model），`stages={"animation"}`；`handler`：从 `ctx.workdir` 按 `upstream/narrative/narrative.json` 里的 `scenes[].id` 顺序读 `animation/scenes/<scene_id>.py`（读取上游只读副本用 `workspace.upstream` 现有能力，本任务只消费，不改 `workspace`），缺失/为空的镜头直接报错（不进引擎），其余交给 `ManimRenderEngine.validate_code`；失败时 `ToolResult(text=..., is_error=True)`，文本里点名具体 `scene_id`。
  - `narrative.json` 的读取需要一个轻量 schema（本任务只取 `scenes[].id`，不需要 T4 fixture 之外定义完整的 pydantic schema——完整 schema 属于 M3 的 `stages.narrative` 产物 schema，这里用 `dict`/`TypedDict` 读取即可，避免跨阶段耦合出一个"提前于 M3 的" schema 模块）。
- **测试**：使用 T4 的 fixture 项目；全部镜头都合法 → 工具返回通过；某镜头文件缺失 → 报错并点名；某镜头代码有语法错误 → 报错并点名（复用 T1 的 traceback 定位能力）。
- **完成标准**：`pytest backend/tests/stages/test_animation_validate.py` 通过。
- **验证命令**：`make check`

### T8：`stages.animation`——`render_preview(scene_id)` 工具（完成）

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

### T9：`stages.animation`——系统提示词完善（完成）

- **目标**：`stages/animation/prompt.md` 从 M1 占位提示词，补齐代码规则、风格组件写法、manim 引擎约束、镜头合并约定，agent 能据此写出不重叠、可校验通过的镜头代码。
- **涉及文件**：`backend/src/studio/stages/animation/prompt.md`（改写）、新建 `backend/src/studio/stages/animation/rules.py`（迁移 `../ai-video/backend/app/codegen_rules.py` 的 `ELEMENT_EXIT_RULES`）、`backend/tests/stages/test_animation_prompt.py`（新建，轻量：断言提示词包含关键章节标题，不做语义测试）。
- **接口与要点**：
  - 提示词内容来源：`ELEMENT_EXIT_RULES`（画面不重叠规则，`rules.py`）、`../ai-video/backend/app/engines/ai/engine_specs/manim.yaml`（引擎约束/画幅规则，237 行，摘取和 manim 代码契约、API 版本相关的部分）、"各镜头代码合并到同一个 Scene 类"的约定说明、`validate_scenes`/`render_preview` 工具的使用时机（写完必须 `validate_scenes`，怀疑视觉问题时用 `render_preview` 自检）。
  - `prompt.md` 是纯文本，`system_prompt()` 方法已存在（`stages/animation/__init__.py`），本任务不改代码只改文案 + 补 `rules.py`。本任务排在 T7/T8 之后，因为提示词要点名这两个工具的用法，工具接口先定下来再写文案更不容易漂移。
- **测试**：提示词包含"画面不重叠"、"validate_scenes"、"render_preview"、"Scene 类"等关键词（粗粒度断言，避免过度测试文案）。
- **完成标准**：`pytest backend/tests/stages/test_animation_prompt.py` 通过；人工通读一遍提示词，确认和设计 §5.3、§8（风格组件经验）一致。
- **验证命令**：`make check`

### T10：api——渲染成片与任务查询/下载端点（完成）

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

### T11：api——成片定稿端点（完成）

- **目标**：用户能"成片定稿"：校验 `final.json` 记录的快照等于当前最新快照后，把动画阶段标记 `finalized`，项目标记完成。
- **涉及文件**：`backend/src/studio/api/jobs.py` 或新建 `backend/src/studio/api/animation.py`（视 T10 路由体量决定拆分与否，决策记录 D5 写清楚放哪）、`backend/src/studio/db/repo/projects.py`（如果"项目标记完成"需要新字段，先确认 `Project` 表是否已有 `completed_at`/`status` 之类字段，没有就走 Alembic 新迁移）、`backend/tests/api/test_animation_finalize.py`（新建）。
- **接口与要点**：
  - `POST /api/projects/{project_id}/animation/finalize-render`：读 `output/final.json` 的 `snapshot_id`，和 `snapshots` 表当前最新快照比较，不一致则 4xx（提示"工作区有未纳入成片的改动，请重新渲染"）；一致则调用 `stage_flow.finalize(..., "animation")`，并把项目标记完成（若 `Project` 无此字段，本任务新增一个 Alembic 迁移，字段和取值记入决策记录）。
- **测试**：`final.json` 快照落后于当前工作区 → 4xx；一致 → 阶段变 `finalized`，项目标记完成。
- **完成标准**：`pytest backend/tests/api/test_animation_finalize.py` 通过。
- **验证命令**：`make check`

### T12：前端——动画画布：镜头列表与预览（完成）

- **目标**：`features/canvas/animation/` 提供镜头列表（状态：已渲染/已过期/校验失败）、代码编辑器（复用 `CodeEditor.vue`）、预览关键帧条。
- **涉及文件**：新建 `frontend/src/features/canvas/animation/AnimationCanvas.vue`、`SceneList.vue`、`KeyframeStrip.vue`，配套 `.spec.ts`（纯逻辑部分，仿 `features/canvas/generic/` 的 `fileKind.ts` 风格拆出 `.ts` 单测）；`frontend/src/types/`（加动画阶段相关类型）；`frontend/src/pages/ProjectWorkbenchPage.vue` 或阶段路由处接入。
- **接口与要点**：
  - 复用 T10 之前已有的通用文件树/编辑器组件读写 `animation/scenes/*.py`（不重新发明文件读写，`features/canvas/generic/FileCanvas.vue` 的模式可以参考甚至部分复用）。
  - 镜头状态来自：`upstream/narrative/narrative.json` 的镜头列表 + 对应 `animation/scenes/<id>.py` 是否存在/最近一次 `validate_scenes`（M2 先不做"最近校验结果"的持久化展示，若无处可查，状态先简化为"文件存在/不存在"，完整的"已校验/已过期"状态跟踪记入决策记录，作为技术债还是本任务范围，执行时判断并记录）。
  - 关键帧展示：调用工具产生的图片走对话事件流（`agent/events.py` 的 `ImageData` 已经会作为工具结果事件落库并通过 SSE 推送），前端画布是否需要单独"重新拉取关键帧"的按钮，还是只在对话里看，执行时按现有 SSE 事件流是否已经够用来判断，避免重复造一条 HTTP 端点。
- **测试**：`.spec.ts` 覆盖镜头状态计算的纯函数；组件层面靠 `make dev` 手动走查（`docs/runbooks/verification.md` 的前端验收约定）。
- **完成标准**：`make dev` 手动打开动画阶段，能看到镜头列表、编辑代码、在对话里触发 `render_preview` 后看到关键帧图片出现在对话流。
- **验证命令**：`pnpm --dir frontend test`；`make dev` 手动走查（截图记入「验证记录」）

### T13：前端——成片面板（完成）

- **目标**：成片面板：渲染成片按钮、任务进度条（轮询 T10 的查询端点）、播放器（`output/final.mp4`）、成片定稿按钮（调 T11）。
- **涉及文件**：新建 `frontend/src/features/canvas/animation/FinalRenderPanel.vue`、`frontend/src/composables/`（加一个任务轮询的 composable，仿现有 TanStack Query hooks 风格）、配套 `.spec.ts`。
- **接口与要点**：
  - 轮询间隔和现有 `jobs` 表设计一致（design §7"worker 的任务进度由 api 每秒轮询一次 jobs 表"是 api↔worker 之间的轮询；前端↔api 的轮询间隔本任务自己定，1 秒起步，`done`/`failed` 后停止轮询）。
  - 渲染成片按钮的禁用条件（例如上一次校验未通过时禁用）在决策记录里写清楚判断依据，避免和 T10 的 api 层校验产生不一致的两套规则。
- **测试**：`.spec.ts` 覆盖轮询状态机（`queued → running → done/failed` 时组件展示什么、何时停止轮询）；手动走查播放器能播放 `final.mp4`。
- **完成标准**：`make dev` 手动走查：点击渲染成片 → 看到进度变化 → 完成后能播放 → 点击成片定稿后阶段状态变化。
- **验证命令**：`pnpm --dir frontend test`；`make dev` 手动走查

### T14：集成验证与风险验证（完成）

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
- 2026-09-28 — T6：`stages.common`——`suggest_upstream_change` 工具与 `suggestions` 仓储 — 完成。新建 `db/repo/suggestions.py`（`create_suggestion`/`get_suggestion`/`list_suggestions`/`update_suggestion_status`，`SuggestionValue` 只读值对象，和 `jobs.py`/`snapshots.py` 同一种写法）；新建 `stages/common/suggest_upstream_change.py`，导出工厂函数 `build_suggest_upstream_change_tool(engine) -> ToolSpec`（不是模块级 `ToolSpec` 常量，见决策记录 D22）；`stages/common/__init__.py` 导出。**未**接入 `AnimationStage.tools()`（决策记录 D22，登记为 TD-32）。`backend/tests/db/test_repo_suggestions.py` 4 个用例、`backend/tests/stages/test_common.py` 3 个用例（新建 `tests/stages/conftest.py` 补 `migrated_engine`/`workdir` fixture，仿 `tests/jobs/conftest.py`）。`make check` 全绿（后端 643 passed / 17 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- 2026-09-29 — T7：`stages.animation`——`validate_scenes` 工具 — 完成。新建 `stages/animation/validate_scenes.py`：`VALIDATE_SCENES_TOOL`（模块级常量，不需要 `Engine`，和 T6 的 `suggest_upstream_change` 工厂函数不同）；`handler` 从 `upstream/narrative/narrative.json` 取 `scenes[].id` 顺序 → 逐个检查 `animation/scenes/<id>.py` 是否存在且非空，缺失/为空的直接报错点名（不进引擎）→ 全部存在时一次性把所有镜头交给 `ManimRenderEngine.validate_code`（`SceneInput.scene_index` 是位置，不认识 `scene_id`）→ `_relabel_scene_errors` 把引擎错误文本里的 `"scene N:"` 前缀换算成对应的 `scene_id`。`stages/animation/__init__.py` 的 `tools()` 从 `return []` 改成 `return list(_TOOLS)`（`_TOOLS` 模块级列表，为 T8 `render_preview` 留了同样接入方式的注释）。新建 `backend/tests/stages/test_animation_validate.py` 6 个用例（全部合法通过、缺失点名、空文件视为缺失、语法错误点名且不误伤未出错的镜头、工具作用域、`upstream/narrative.json` 还没物化时报 `is_error` 而不是让异常冒出去），用 T4 的 `animation_project` fixture + 手动 `materialize_upstream` 模拟 `TurnRunner` 轮次开始前的物化。发现并记录了一个 pyright/pytest 对同名 `conftest` 模块解析不一致的坑（决策记录 D25、意外与发现），本文件用本地 `Protocol` 结构类型绕开，T8 的测试文件在同一目录下会遇到同样的坑，直接抄这个模式。`make check` 全绿（后端 648 passed / 18 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- 2026-09-29 — T8：`stages.animation`——`render_preview(scene_id)` 工具 — 完成。新建 `stages/animation/render_preview.py`：`RENDER_PREVIEW_TOOL`（模块级常量，不需要 `Engine`，接入方式同 T7）；`handler` 读 `upstream/narrative/{narrative.json,timing.json}` → `scene_id` 不在 `narrative.json` 里直接报错（不进引擎）→ 为 `0..target_scene_index`（含）每个镜头构造 `SceneInput`（代码读取/缺失判断复用 T7 同款逻辑，缺失时点名报错）→ 每个镜头的 `SceneAudio.audio_path` 用 `files.safe_path(ctx.workdir, f"upstream/{timing.audio_path}")` 拼出**绝对路径**（`timing.json` 里的 `audio_path` 是叙事阶段自己工作区里的相对路径，物化后真实文件在 `upstream/` 之下；`ManimRenderEngine` 把这个值原样嵌进生成脚本源码当字面量，脚本又是在临时目录里当 cwd 跑子进程，传相对路径会找不到文件——"下一步"一节点出的坑，实测按提示写一次就对了，没有绕路）→ 调用 `ManimRenderEngine().render_preview`→ `success=False` 原样转 `is_error=True` 的 `ToolResult`（超时时 `error_message` 已经是"预览渲染超时"）→ 成功时把 `PreviewKeyframe.png_bytes` 转 base64 装进 `ToolResult.images`（`ImageData(media_type="image/png", ...)`），文本拼渲染/配音时长与偏差。`stages/animation/__init__.py` 的 `_TOOLS` 加上这个工具。新建 `backend/tests/stages/test_animation_preview.py` 5 个用例（工具作用域；`@pytest.mark.slow` 的端到端用例——对 `s-explain` 调用工具，断言 `images` 数量等于该镜头 beat 数（2）、文本含镜头 id 和"偏差"；`scene_id` 不存在报错点名；镜头代码缺失报错点名；引擎超时——用 `monkeypatch.setattr(ManimRenderEngine, "render_preview", ...)` 直接替换成一个返回 `success=False, error_message="预览渲染超时"` 的假实现，不真的等一次超时渲染，验证工具层把它原样转成 `is_error=True`，这条超时路径的引擎层行为已经由 T2 的 `test_render_preview_times_out_without_waiting_120_seconds` 覆盖）。`make check` 全绿（后端 652 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）；额外单独跑 `pytest backend/tests/stages -m slow` → `2 passed`（T7+T8 各一条端到端渲染用例）。
- 2026-09-29 — T9：`stages.animation`——系统提示词完善 — 完成。新建 `stages/animation/rules.py`（迁移 `ELEMENT_EXIT_RULES` 常量，文案不改，只改模块 docstring）；改写 `stages/animation/prompt.md`（从 6 行占位扩到完整提示词），内容包括：输入产物清单、"镜头代码合并到同一个 `MainScene`"约定（按实际的 `script.py` 行为写——自动跨镜头变量提升为 `self.` 属性、`clear_except`、自动补齐 `self.wait` 到配音时长这几条都核对过 `engine.py`/`script.py` 现有实现，不是照抄旧项目文档）、`ELEMENT_EXIT_RULES` 原文整段嵌入、设计 §5.5"风格组件的编写经验"四条（布局骨架/图标克制/转场不留中间态/避免角落堆放）、manim.yaml `code_prompt` 字段里摘取的代码契约高频报错点（版本声明、`set_stroke`/`Sector`/`path_arc`/`rate_func`/`DecimalNumber` 双动作崩溃/坐标必须三元素/中英文字体分工/禁止外部资源/`VGroup` 双重定位等，跳过了`narrative_hint` 字段和只对旧提示词-JSON 输出格式有效的两段——见「意外与发现」）、画布安全区、beat 时间窗口"演满"原则、`validate_scenes`/`render_preview` 工具的使用时机、定稿前自检清单。**不改** `stages/animation/__init__.py` 的 `system_prompt()`（按任务要求保持"直接读 `prompt.md` 全文返回"不变），`rules.py` 和 `prompt.md` 的一致性由测试保证而不是代码耦合（决策记录 D27）。新建 `backend/tests/stages/test_animation_prompt.py` 8 个用例：`ELEMENT_EXIT_RULES.strip()` 逐字包含于 `system_prompt()`；分别断言含"画面不重叠"/`validate_scenes`/`render_preview`/`Scene`+"合并"/"Manim Community v0.20.1"/四条风格经验关键词；外加一条 `rules.ELEMENT_EXIT_RULES` 自身非空的单测。写完后人工通读一遍 `prompt.md` 全文，过程中发现 `suggest_upstream_change` 实际还没接入 `AnimationStage.tools()`（D22/TD-32），原草稿在"工具使用时机"一节提到了这个工具，通读时改成不提示 agent 调用它（决策记录 D28），避免提示词引导 agent 调用一个实际不存在于其工具列表的函数。`make check` 全绿（后端 660 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- 2026-09-29 — T10：api——渲染成片与任务查询/下载端点 — 完成。新建 `api/jobs.py`：`POST /api/projects/{id}/render`（按 D4 只检查动画阶段状态不是 `locked`，不重复跑 `validate_scenes`，返回 201 + `JobOut`）、`GET /api/projects/{id}/jobs/{job_id}`（任务不属于该项目视为不存在，404）、`GET /api/projects/{id}/output/final.mp4`（只看 `output/final.mp4` 是否存在就返回 `FileResponse`，不额外检查 job 状态是否 `done`——同一条"不重复判断逻辑"思路的延伸，决策记录 D29）。`api/schemas.py` 加 `JobOut`（`JobValue` 的子集，不含 `payload`/`heartbeat_at` 这两个 worker 内部字段，决策记录 D30）。`main.py` 挂载新路由。新建 `backend/tests/api/test_jobs.py` 9 个用例，复用 T4 的 `seed_animation_project`（直接传 `api_env.app.state.engine`/`blobs`/`data_dir`，不经过 api 层建项目，因为 M3 narrative agent 还没实现，这是唯一能拿到"动画阶段 active"项目的路径）覆盖：创建任务成功返回 `queued`；`locked` 阶段创建任务 409；未知项目 404；查询任务（含跨项目查询 404）；下载成片成功（`Content-Type: video/mp4`）和成片未渲染时 404。**未**触碰 TD-32/D22（`suggest_upstream_change` 接入 `AnimationStage.tools()`）——T10 的三个端点都不需要往阶段的 `tools()`/`ToolContext` 传 `Engine`（"下一步"标注为可选顺手项，不是强制要求），留给真正碰到这个需求的任务处理。`make check` 全绿（后端 669 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- 2026-09-29 — T11：api——成片定稿端点 — 完成。`Project` 表新增 `completed_at` 列（新迁移 `0003_projects_completed_at.py`，`op.add_column`/`op.drop_column`，写法照抄 `0002`），`db/repo/projects.py` 的 `ProjectValue` 补上这个字段并新增 `mark_project_completed(engine, project_id) -> ProjectValue`（设为 `datetime.now(UTC)`，同 `stages.repo` 的写法风格）；`api/schemas.py` 的 `ProjectOut` 同步加 `completed_at`，`api/projects.py::_project_out` 传这个字段。新建 `api/animation.py`：`POST /api/projects/{id}/animation/finalize-render`——读 `output/final.json` 的 `snapshot_id`，与 `db.repo.snapshots.latest_snapshot` 比较，不一致或文件不存在都是 4xx（分别是"工作区有未纳入成片的改动，请重新渲染"409 和"成片尚未渲染完成，无法定稿"404），一致则复用 `api/projects.py::finalize_stage_endpoint` 已在用的 `stage_flow.finalize`（`StageFlowError` 转 409），成功后 `mark_project_completed`。执行中发现"下一步"里"走 `workspace.files.read_text` 读 `output/final.json`"这条实测走不通（决策记录 D32/意外与发现）：`output/` 是 `workspace.layout.HIDDEN_TOP_DIRS` 之一，`read_text` 对隐藏顶层目录会主动抛 `ScopeError`；改成和 T10 的 `download_final_video_endpoint` 一样直接用 `pathlib` 读工作区文件。`main.py` 挂载新路由。新建 `backend/tests/api/test_animation_finalize.py` 4 个用例（未渲染过 404；渲染后工作区又有改动——手动写一个镜头文件再 `create_snapshot` 制造"比 final.json 记录的快照更新"的场景——409；快照一致时 200，阶段变 `finalized` 且通过 `GET /api/projects/{id}` 看到 `completed_at` 非空；未知项目 404）；`backend/tests/db/test_migrate.py` 补一条 `completed_at` 列存在性断言。T11 复核 D22/TD-32：`finalize_render_endpoint` 走的是 `stage_flow.finalize`，不经过 `AnimationStage.tools()`/`ToolContext`，同样没有出现"顺手解决"的时机，继续搁置。`make check` 全绿（后端 674 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- 2026-09-29 — T12：前端——动画画布：镜头列表与预览 — 完成。新建 `features/canvas/animation/`：`AnimationCanvas.vue`（主组件，仿 `FileCanvas.vue` 的缓冲区状态机）、`SceneList.vue`（纯展示）、`KeyframeStrip.vue`（静态提示，见 D39）、`narrativeScenes.ts`+`sceneStatus.ts`（镜头列表数据）、`keyframeHint.ts`、`conflictState.ts`+`missingFile.ts`（从 `generic/` 复制，见 D36）；`CodeEditor.vue` 从 `features/canvas/generic/` 挪到 `components/CodeEditor.vue`（新建 `components/codeEditorLanguage.ts` 载 `EditorLanguage` 类型），`fileKind.ts`/`FileCanvas.vue` 同步改 import（决策记录 D36：实测 ESLint 的 `features/* 之间互不 import` 规则挡住跨阶段画布复用，这是规则自己建议的解法）。`ProjectWorkbenchPage.vue` 按 `stage === 'animation'` 分派到 `AnimationCanvas`，其它阶段仍用 `FileCanvas`。新增 23 个前端单测（`narrativeScenes`/`sceneStatus`/`keyframeHint`/`conflictState`/`missingFile` 各自的 `.spec.ts`），前端总计 151 passed。`make dev` 手动走查（用 M2 T4 的 `seed_animation_project` 绕过 M3 seed 出项目，真实调用 `validate_scenes`/`render_preview` 而不是伪造数据，见「验证记录」）发现并修复一个真实的响应式竞态 bug（D40：保存新镜头代码后编辑器被误判"文件消失"关闭）。`KeyframeStrip.vue` 不显示真实缩略图（决策记录 D39/TD-21 复核：图片内容从 M1 起就没有持久化，只有 `media_type`），只给指向对话面板"含 N 张图片"计数的静态提示；镜头状态只做"代码是否存在"，不做"已校验/已过期"（决策记录 D38，登记为 TD-33）。走查过程中发现并绕开一个环境问题：Browser pane 的 `preview_start` 按 `.claude/launch.json` 相对 `cwd` 解析到了主仓库而不是当前 worktree（详见「意外与发现」），改用 Bash 直接在 worktree 里起 `uvicorn`/`vite`，`navigate` 打开。`make check` 全绿（后端 674 passed / 19 deselected，前端 21 files / 151 passed，import-linter 21 kept，pyright 0 errors）。
- 2026-09-29 — T13：前端——成片面板 — 完成。新建 `FinalRenderPanel.vue`（渲染成片按钮 + 进度条 + 播放器 + 成片定稿按钮），挂进 `AnimationCanvas.vue` 镜头列表/编辑器 grid 下方，只在镜头列表已知（`narrativeMaterialized && !narrativeParse.error`）时显示；新建纯逻辑模块 `renderJobState.ts`（`isJobInFlight`/`isRenderButtonDisabled`/`canFinalize`/`jobStatusLabel`）+ 配套 `.spec.ts`（决策记录见下）。前端此前完全没有 job/render/final 相关的类型和客户端函数，从这一层开始补齐：`types/api.ts` 加 `JobOut`，`ProjectOut` 补 `completed_at`（后端 T11 已经加了这个字段，前端类型这次才补上，此前一直没同步）；`api/endpoints.ts` 加 `createRenderJob`/`getJob`/`finalizeRender`/`finalVideoUrl`（后者只拼 URL 给 `<video src>` 用，不专门写 fetch 函数下载字节，同 `sessionStreamUrl` 的做法）；`composables/queries.ts` 加 `queryKeys.job`、`jobRefetchIntervalMs`（纯函数：`queued`/`running` 时返回 1000，否则 `false`，供 `useJobQuery` 的 `refetchInterval` 用，`done`/`failed` 后自动停止轮询）、`useCreateRenderJobMutation`/`useJobQuery`/`useFinalizeRenderMutation`。新增 14 个前端单测（`renderJobState.spec.ts` 5 条、`queries.spec.ts`/`endpoints.spec.ts` 各新增若干）。`make check` 全绿（后端 674 passed / 19 deselected 不变，前端 22 files / 165 passed，import-linter 21 kept，`vue-tsc`/pyright 0 errors，lint 0 警告）。L4 浏览器走查（真实起 api + worker + frontend 三个进程，绕开 T12 记录的 `preview_start` 坑，见「意外与发现」）：种子一个"叙事已定稿"项目 → 用 `fake` runtime 发一条消息物化 `upstream/narrative/`（镜头列表出现 `s-hook`/`s-explain`，均"待编写"）→ 逐个打开编辑器写入 `self.add(Dot())`/`self.add(Square())` 并保存（两次都一次成功，没有复现 T12 记录的 D40 竞态）→ 点击"渲染成片"：按钮立即变禁用、状态文案显示"排队中"→ 真实起的 worker 进程领取并渲染（`manim`/`ffmpeg` 子进程日志核实，`worker.log` 显示"镜头 s-explain 渲染完成""任务 ... 完成"）→ 面板 1 秒轮询自动追到 `done`：进度条填满、状态文案"已完成"、`<video>` 出现且 `GET .../output/final.mp4` 网络记录显示 206 Partial Content；点击播放后用 `javascript_tool` 读 `video` 元素属性确认真实播放到底（`currentTime === duration === 3.03`、`ended: true`），不是只看到一个空播放器 → 点击"成片定稿"：`POST .../animation/finalize-render` 网络记录 200，阶段导航从"动画"变"动画✓"，右上角按钮从"定稿"变"重新打开"，面板标题栏出现"项目已完成"，`curl GET /api/projects/{id}` 确认 `completed_at` 非空。完整复现了完成标准要求的四步链路（点击渲染成片→看到进度变化→完成后能播放→点击成片定稿后阶段状态变化）。
- 2026-09-29 — T14：集成验证与风险验证 — 完成，**M2 计划全部任务（T1–T14）已完成**。新建 `backend/tests/api/test_animation_flow.py`（`@pytest.mark.slow`），用真实 `TurnRunner` + `FakeRuntime` 脚本（`write` 两个镜头代码 + `call_tool("validate_scenes")` + `call_tool("render_preview", {"scene_id": "s-explain"})`）跑一轮真实 turn，断言轮次事件流里两次工具调用的 `tool_result`（校验通过文本、2 张关键帧 + 偏差文本）→ `POST /render` 创建任务 → `worker.run_once` 产出 `output/final.mp4`/`final.json` → `GET /jobs/{id}` 确认 `done` → `GET /output/final.mp4` 确认可下载 → `POST /animation/finalize-render` 确认阶段变 `finalized`、`GET /projects/{id}` 确认 `completed_at` 非空——完整串起 T4/T7/T8/T5/T10/T11 的产物，一次跑通，没有踩到计划外的新坑（决策记录 D44）。`test_manim_engine.py` 按计划要求补了一句引用说明（指向 T2 的关键帧测试和本条端到端测试），不重复写第三份"渲染极小镜头"用例。复核设计 §9 风险表：R1–R5 明确是 M1 范围且已完成，T14 执行过程中没有发现任何新的风险假设不成立，不触发 SOP §6 升级条件。AC4、AC7 在本次打勾。`pytest backend/tests/api/test_animation_flow.py -m slow` → `1 passed`；`pytest backend/tests -m slow` → `14 passed`（含 T14 新增这条）；`make check` 全绿（后端 674 passed / 20 deselected，前端 22 files / 165 passed，import-linter 21 kept，pyright/vue-tsc 0 errors）。
- 2026-09-29 — 代码评审（SOP §3 阶段 5） — 完成。独立 subagent 评审 `44e7dd3..4340e3a` 全部 14 个 commit，发现并修复一处 Important（`reopen` 动画阶段未清 `Project.completed_at`），一处 Minor 登记为 TD-35 暂不修（决策记录 D45）。`make check` 全绿（后端 675 passed / 20 deselected）。见本次提交。

## 下一步

**M2 计划的全部任务（T1–T14）已经完成，全部验收标准（AC1–AC7）都已打勾；SOP §3
阶段 5（评审）也已完成并处理了发现。** `make check` 全绿（后端 675 passed /
20 deselected，前端 22 files / 165 passed，import-linter 21 kept，pyright/vue-tsc
0 errors），`pytest backend/tests -m slow` 14 个慢测试全部通过。

**评审记录**（2026-09-29，独立 subagent，不是写这些代码的上下文；范围
`44e7dd3..4340e3a` 全部 14 个 commit）：评审者自己跑了一遍 `make check` 和
`pytest backend/tests -m slow`，数字和计划里记录的完全一致；确认决策记录
D1–D44 里的每一条偏离计划原文的决定都有对应的技术理由，逐条核对了几个关键决定
（D11 的 jobs.repo 转发、D25/D26 的 pyright/pytest conftest 解析分歧绕开方式、
D36 的 CodeEditor.vue 搬家、D22/TD-32 的诚实搁置）没有发现"看似合理但实际不成立"
的情况。发现两条问题：
- **Important（已修复，决策记录 D45）**：动画阶段定稿后如果用户点"重新打开"
  （`POST /stages/animation/reopen`，M1 就有的通用端点），`Project.completed_at`
  不会被清空——工作区已经又能改、成片不再代表当前状态，但前端 `FinalRenderPanel.vue`
  仍会显示"项目已完成"。修复：`db/repo/projects.py` 新增 `clear_project_completed`
  （`mark_project_completed` 的反操作），`api/projects.py::reopen_stage_endpoint`
  在 `stage == "animation"` 时调用它——`stage_flow.reopen()` 本身保持和阶段无关
  的通用逻辑不变，"项目完成"是动画阶段特有的语义，对称地放在 api 层处理（和
  `completed_at` 最初就是在 `api/animation.py`（animation 专属端点）里设置的，
  不是在通用的 `finalize_stage_endpoint` 里，是同一个思路）。新增测试
  `test_animation_finalize.py::test_reopening_animation_after_finalize_clears_completed_at`
  （先红后绿）。
- **Minor（评估后不修，登记为 TD-35，决策记录 D45）**：`POST /render` 不检查
  项目是否已有一条 `queued`/`running` 的同类任务，理论上能重复排队；单 worker
  顺序处理不会写坏文件，只是白渲染一次，投入产出比不划算，暂不修。

「declined to judge」列表（多进程 job 队列并发正确性、TD-32/33/34、`run_once`
快照-渲染顺序的极窄 TOCTOU 窗口、agent 生成代码经子进程执行是产品设计本身而
非本计划引入的漏洞、`async def` 路由里同步 DB 调用阻塞事件循环）都是既有的、
已登记或明确超出本计划范围的问题，评审判断不需要处理，本次会话复核后同意。

本计划不需要新会话继续写代码。接下来按 SOP §3 走：

1. ~~**阶段 5：评审**~~（已完成，见上）。
2. **阶段 6：人验收**——AI 向负责人演示（`make dev` 走一遍 T12/T13 记录的浏览器
   操作序列，或直接看「验证记录」），负责人确认。**这一步需要负责人明确同意，
   不能由 AI 自己判断"验收通过"。**
3. 验收通过后，按 **SOP §7 收尾清单**处理（这些都不是任务循环的一部分，
   需要负责人先验收，本次会话不执行）：
   - [ ] 勾选 SOP §7 清单里"计划中所有任务都已勾选，「验证记录」完整"（本次
     已满足，见上）。
   - [ ] 计划从 `plans/active/` 移到 `plans/completed/`，状态改为「已完成」。
   - [ ] 影响范围超出本计划的决定是否需要写成 ADR（复核 D1–D44，目前判断都是
     本计划内部的实现决定，没有发现需要单独写 ADR 的项；收尾时可以再复核一次）。
   - [ ] `docs/ARCHITECTURE.md` 与代码实际结构是否一致（T1/T3/T5 各自新增过
     import-linter 契约，执行过程中已同步更新，收尾时再扫一遍）。
   - [ ] `docs/quality/QUALITY.md` 是否需要补上 `engines.render`/`jobs`/
     `worker`/`stages.animation` 几个新模块的评级。
   - [ ] `docs/quality/tech-debt.md` 是否已经登记 TD-32（`suggest_upstream_change`
     未接入 `AnimationStage.tools()`）、TD-33（镜头状态无"已校验/已过期"跟踪）、
     TD-34（成片面板刷新后不恢复任务进度）——这三条本计划执行中已经登记，
     收尾时确认条目还在、描述准确。
   - [ ] `docs/references/` 是否已经收录本计划验证过的 SDK/工具行为
     （manim 音轨 1 秒静音下限、ffmpeg 编译缺 libass 等，已在 T2/T5 写入
     `references/manim.md`/`references/ffmpeg.md`）。
   - [ ] `AGENTS.md` 里的命令和链接是否仍然有效（`make dev` 现在起三个进程，
     `AGENTS.md` 已在 T5 同步）。
   - [ ] 分支 `m2-animation` rebase 到最新 `main`，跑一次完整 `make check`，
     以 `--no-ff` 合并到 `main`。**本次会话不执行这一步**——AGENTS.md/任务
     指令明确这需要负责人先验收，不是执行者能自行决定的事。

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
- 2026-09-28 — D22（T6）：T6 的"下一步"留了一个需要自行判断的点——`suggest_upstream_change` 要不要在 T6 就接进 `AnimationStage.tools()`。判断结果：**不接**。理由：`suggest_upstream_change` 的 `handler` 要写 `suggestions` 表，必须拿到一个 `Engine`；但 `StageDefinition.tools()`（`agent/stage.py`）是零参数方法，调用链上 `TurnContext`/`ToolContext`（`agent/runtime.py`/`agent/tools.py`）都没有携带 `Engine` 的字段，`main.py` 里 `AnimationStage()` 也是在拿到 `engine` 之前就实例化的模块级单例。要把 `engine` 真正传到 `AnimationStage.tools()` 或 `ToolContext`，需要改 `ToolContext`/`TurnContext` 的字段（或者改 `StageDefinition.tools()` 的签名、改 `main.py` 的阶段装配方式）——这些都是 T6"涉及文件"列表之外的公共接口，属于红线"不改变计划之外的公共接口"。而且 T7/T8（`validate_scenes`/`render_preview`）按计划规格只用 `ctx.workdir`，不需要 `Engine`，所以这条线也不会在 T7–T9 自然补上。因此 T6 只把 `suggest_upstream_change` 做成一个独立可用、有完整测试覆盖的工具（工厂函数 `build_suggest_upstream_change_tool(engine) -> ToolSpec`，不是模块级常量，因为要闭包绑定 `engine`），暂不接线；接线所需的"阶段工具怎么拿到 db engine"这件事登记为技术债 TD-32，留给会真正碰到这个需求的后续任务（M2 剩余任务或 M3）决定方案。
- 2026-09-29 — D23（T7）：`validate_scenes` 的 handler 检查镜头代码时，只要 `narrative.json` 里任意一个镜头对应的 `animation/scenes/<id>.py` 缺失或为空，就整体报错（点名全部缺失的 `scene_id`）并直接返回，不再调用 `ManimRenderEngine.validate_code`——即使其余镜头代码都已经写好。理由：T7 计划正文第 2/3 条本身就是顺序表述（"缺失/为空的镜头直接报错（不进引擎）"→"都存在的镜头，交给 `validate_code`"），读作"只有全部镜头都存在时才进入第 3 步"；`validate_code` 需要按 `scene_index` 位置连续编号（跨镜头名称提升 `_promote_cross_scene_names` 等逻辑依赖完整、连续的镜头序列），部分镜头缺失时硬凑一个不连续的 `SceneInput` 列表去校验，其正确性没有意义，也会让"缺失"和"语法错误"两类问题的报错混在一起，不如分两步：先保证"每个镜头都有代码"，再保证"代码本身没问题"。
- 2026-09-29 — D24（T7）：`stages/animation/validate_scenes.py` 的 `ManimRenderEngine.validate_code` 返回的错误文本用形如 `"scene N: ..."`（英文 "scene"，`N` 是 `SceneInput.scene_index`）的前缀点名出错镜头（`engines/render/manim/script.py` 的 `_label_with_scene`/`process.py` 的 `run_dry_run` 都是这个格式，是 T1/T2 定下的、engines 层完全不认识 `scene_id` 这个概念的既有约定）。`validate_scenes` 的 `_relabel_scene_errors` 用正则 `r"scene (\d+):"` 把这个前缀替换成 `"镜头 <scene_id>（scene N）:"`，不改动原始错误文本剩余部分（traceback/pyflakes 消息原样保留，方便照原样定位问题行号）。这个正则约定只在 `stages.animation` 内部使用，不改变 `engines.render` 任何对外接口。
- 2026-09-29 — D25（T7）：`backend/tests/stages/test_animation_validate.py` 不用 `from conftest import AnimationProjectEnv` 引入顶层 `conftest.py`（D13）里定义的 fixture 值对象类型，改成在测试文件内定义一个结构等价的 `typing.Protocol`（`project_id`/`workdir`/`engine`/`blobs` 四个字段）。原因见「意外与发现」：`pyright` 和 `pytest` 对 `tests/stages/` 目录里裸写 `import conftest`/`from conftest import ...` 解析到不同的模块（`pyright` 优先匹配同目录的 `tests/stages/conftest.py`，`pytest` 运行时实际用的是 rootdir 插入的顶层 `tests/conftest.py`），两者不一致时 `pyright` 会报"未知导入符号"。用 `Protocol` 结构类型只依赖字段名和类型匹配，不依赖具体导入哪个模块，绕开这组冲突；运行时传入的仍然是真正的 `conftest.AnimationProjectEnv` dataclass 实例，`Protocol` 只在静态检查时起作用，不改变任何运行行为。后续任何要放进 `backend/tests/stages/`（或其它带 `__init__.py` 的测试子目录）、又要引用顶层 `conftest.py` 里定义的类型的测试文件，都会遇到同样的问题，抄这个 `Protocol` 模式即可。
- 2026-09-29 — D26（T8）：T8 的"下一步"留了两个需要自行判断的点，执行结果：(1) `test_animation_preview.py` 里的 `AnimationProjectEnv` **各自定义一份**本地 `Protocol`（同 D25），不 `from .test_animation_validate import AnimationProjectEnv` 跨测试文件导入——两个测试文件除了这四个字段名的类型声明外没有其它耦合，各自定义一份的重复成本（4 行）远低于"测试文件之间互相 import"带来的隐性耦合（以后改一个文件的内部结构要担心另一个文件）。(2) 引擎超时路径在工具层的测试用 `monkeypatch.setattr(ManimRenderEngine, "render_preview", <假实现>)` 直接替换掉整个方法，让它立即返回 `PreviewResult(success=False, error_message="预览渲染超时", ...)`，不引入任何真实渲染或等待——因为工具层要保证的行为只是"engine 返回 success=False 时不篡改 is_error"，这个断言不需要真的触发一次超时，T2 的 `test_render_preview_times_out_without_waiting_120_seconds` 已经完整覆盖了"引擎真的会在超时后返回这个结果"这件事，工具层测试重复验证引擎行为没有增量价值。
- 2026-09-29 — D27（T9）：`stages/animation/rules.py` 的 `ELEMENT_EXIT_RULES` 常量和 `prompt.md` 之间**不建立代码耦合**（不改 `stages/animation/__init__.py` 的 `system_prompt()` 去拼接这个常量），改成把常量文案手动、逐字复制进 `prompt.md`，两处的一致性由 `test_animation_prompt.py::test_system_prompt_embeds_element_exit_rules_verbatim` 断言（`ELEMENT_EXIT_RULES.strip() in system_prompt()`）保证——理由：任务指令明确要求"不改代码逻辑，`system_prompt()` 已存在，直接读 `prompt.md` 全文返回"，本任务的"涉及文件"也只列了 `prompt.md`（改写）和新建的 `rules.py`，没有列 `__init__.py`；用测试做"单一事实来源"的一致性检查，比引入一条运行时拼接逻辑更贴合这条指令，且任何未来编辑 `prompt.md` 这一段又没同步改 `rules.py`（或反过来）都会在 `make check` 直接暴露，不依赖人工记忆。
- 2026-09-29 — D28（T9）：`prompt.md`"工具使用时机"一节**不提**让 agent 调用 `suggest_upstream_change`——虽然计划正文 T9 小节和设计 §5.3 都把它列在动画阶段的工具里，但 T6 的决策记录 D22/技术债 TD-32 已经记录这个工具至今没有接入 `AnimationStage.tools()`（需要 `Engine`，`tools()` 是零参数方法拿不到）。人工通读 `prompt.md` 时发现草稿版本点名了这个工具的调用方式，但 agent 实际拿到的工具列表（`AnimationStage.tools()`）里没有它，会诱导 agent 尝试调用一个不存在的函数。改成"发现问题源头在上游时，在回复里明确指出问题并向用户说明"，不改变工具接线现状（T9"涉及文件"没有 `stages/animation/__init__.py` 的 `tools()`），等 T10/T11 或以后实际解决 TD-32 时再把这段说明换回来。
- 2026-09-29 — D29（T10）：`GET /api/projects/{id}/output/final.mp4` 不检查 job 状态是不是 `done`，只看 `output/final.mp4` 文件本身是否存在——如果去查"最新一条 `final_render` job 是不是 done"，等于在"文件是否存在"之外又建了一套关于"成片是否已经渲染好"的判断依据，两者本该永远一致但没有任何机制强制这一点（比如手工放测试用的 `final.mp4`、或者以后允许直接拷贝文件恢复成片这类边界情况，都会让两者不同步）。延续 D4"不重复一份判断逻辑"的思路：文件系统上的存在性就是唯一事实来源，端点只做它字面上说的事——"这个文件有没有，有就给"。
- 2026-09-29 — D30（T10）：`JobOut` 不包含 `JobValue` 的 `payload`/`heartbeat_at` 两个字段——`payload` 是 T10 创建任务时特意留白的口子（决策记录 D21 提到，worker 目前只靠 `project_id` 定位项目），本任务没有往里面塞任何内容，暴露一个恒为 `None`/空的字段没有意义；`heartbeat_at` 是 worker 内部"有没有卡死"的信号，前端轮询只需要 `status`/`progress`/`error`/`result` 就能画出完整的进度 UI（design §7），不需要关心心跳时间戳。以后如果前端真的需要展示心跳（比如"上次更新于 N 秒前"），再加字段，不是本任务的完成标准要求的。
- 2026-09-29 — T10 复核 D22/TD-32：三个新端点（创建渲染任务、查询任务、下载成片）分别只需要 `Engine`（DB）和 `Settings`（读工作区路径），都不经过 `AnimationStage.tools()`/`ToolContext`，所以没有出现"顺手解决"的时机——`suggest_upstream_change` 接入阶段工具列表这件事和"api 层怎么触发渲染/查询任务"是两条不相交的路径。TD-32 继续保留，留给会真正用到"阶段工具拿到 db engine"的任务（M2 剩余任务或 M3）处理。
- 2026-09-29 — D31（T11）：新建 `backend/src/studio/api/animation.py`，不追加进 `api/jobs.py` —— `jobs.py` 的三个端点（创建渲染任务/查询任务/下载成片）语义上都围绕"`jobs` 表这条任务记录"；`finalize-render` 端点不读写 `jobs` 表（它读的是 worker 产出的 `output/final.json` 文件），核心动作是复用 `stage_flow.finalize` 走"阶段定稿"流程，语义上更接近 `api/projects.py` 里的 `finalize_stage_endpoint`（同一个 `finalize` 函数、同一种 `StageFlowError → 409` 处理），只是这条定稿路径多了一步"校验快照"和"标记项目完成"的前置/后置逻辑，值得单独一个模块承载，而不是让 `jobs.py` 承担两种不同的职责（任务队列 CRUD + 阶段定稿）。
- 2026-09-29 — D32（T11）：`finalize_render_endpoint` 读 `output/final.json` 直接用 `pathlib`（`final_json_path.read_text(...)` + `json.loads`），不走"下一步"原文写的 `workspace.files.read_text` —— 实测 `workspace.files.read_text` 对 `HIDDEN_TOP_DIRS`（`.cache/`、`output/`，`workspace/layout.py:13-15`）下的路径会主动抛 `ScopeError`（"路径不可读"），`output/final.json` 正好落在这个范围内，这条路径走不通（见「意外与发现」）。改成和 T10 的 `download_final_video_endpoint` 完全一样的处理方式：`project_dir(settings.data_dir, project_id) / "output" / "final.json"`，直接用标准库读——`output/` 对 agent 工具和文件浏览 api 隐藏是因为它是"worker 产物，不是工作区内容"，但 `api` 层读 worker 产物本身不应该受这层限制，T10 已经确立了这个先例。
- 2026-09-29 — D33（T11）：新字段命名为 `Project.completed_at: datetime | None`（`None` 表示未完成，非空即完成时间）——和 `ProjectStage.finalized_at` 同一种"时间戳即状态"的表达方式（不用额外的 `is_completed: bool`），一次读出"是否完成"和"什么时候完成"；`mark_project_completed(engine, project_id)` 每次调用都覆写成当前时间（`datetime.now(UTC)`，同 `db.repo.projects` 其它地方的时间处理方式），不做"已完成就不再更新"的保护——本计划的调用路径（`finalize_render_endpoint` 成功定稿后）只会在快照比较通过后触发一次，不存在需要保护的重复调用场景，真出现"重新渲染后再定稿一次"的需求时，覆写时间戳语义上也是对的（"最近一次确认完成的时间"）。
- 2026-09-29 — D34（T11）：`finalize_render_endpoint` 写成 `async def` 并复用 `_require_not_busy(turn_runner, project_id)`（本地重新实现了一份和 `api/projects.py` 同名同逻辑的私有函数，未跨模块导入——两个 `api` 模块之间不建立横向依赖，符合 `api` 内部各路由文件互相独立的既有风格，`api/jobs.py` 和 `api/projects.py` 之间也没有互相导入）——`finalize()` 会写快照/阶段状态，和 `finalize_stage_endpoint` 是同一类"先查忙碌再写工作区"的端点（`api/projects.py` 模块文档的"项目级串行（I4）"约定），理应同样受 `TurnRunner.is_project_busy` 保护，避免和一轮正在跑的 turn 产生竞态。
- 2026-09-29 — D35（T11）：`api/schemas.py::ProjectOut` 同步加 `completed_at` 字段（`api/projects.py::_project_out` 传值）——`Project` 表新增的字段如果不出现在任何响应里，前端拿不到"项目是否完成"这个信息，T13（成片面板）以后如果要展示"项目已完成"状态就得再补一次这层传递；`ProjectOut` 是"项目行的标准表示"，其它字段（`current_stage` 等）都在这里，新字段没有理由例外，加进去成本也只是两行。这不改变任何现有响应字段，向后兼容。
- 2026-09-29 — D36（T12）：`CodeEditor.vue` 从 `features/canvas/generic/` 挪到 `components/CodeEditor.vue`，`EditorLanguage` 类型拆进新建的 `components/codeEditorLanguage.ts`——计划正文写"代码编辑器（复用 `CodeEditor.vue`）"，但用一个探针文件对 `pnpm lint` 实测确认：ESLint 的 `features/* 之间互不 import` 规则按 `@/features/**` 整体匹配，不区分是否属于同一个上级目录（`features/canvas/generic/` 和 `features/canvas/animation/` 都在 `features/canvas/` 下，但规则不认这个"同一个 canvas 大类"的关系），跨阶段画布互相 import 会被直接拦下。`frontend/eslint.config.ts` 里这条规则自己的报错文案就是"共用内容放进 `components/` 或 `composables/`"，把 `CodeEditor.vue` 搬进 `components/`（新增 `codeEditorLanguage.ts` 载它依赖的 `EditorLanguage` 类型，`features/canvas/generic/fileKind.ts` 改成从那里 import 再重新导出，保持自己原有的对外接口）正是这条规则建议的解法，改动小（移动一个文件 + 两处 import 路径），`FileCanvas.vue` 功能不变（128 个既有前端测试全部保持通过）。`conflictState.ts`/`missingFile.ts` 这两个更小的状态机（各 < 40 行、逻辑已经在通用画布里验证过）**没有**同样搬进 `components/`：它们是"文件编辑缓冲区业务状态机"而不是 UI 组件，硬塞进语义上只该装可复用组件的 `components/` 不合适；复制一份到 `features/canvas/animation/`（各自保留独立的 `.spec.ts`）成本低（各 < 80 行含注释），参照 T7/T8 决策记录 D25/D26 同样的取舍——宁可重复几十行稳定代码，也不为了单单这一处复用制造新的跨 feature 耦合面。
- 2026-09-29 — D37（T12）：镜头列表数据来源——前端直接用已有的通用文件端点读 `upstream/narrative/narrative.json`，用新建的 `narrativeScenes.ts::parseNarrativeSceneIds` 在客户端解析出 `scenes[].id`，不新增"列出镜头"端点（后端目前也没有，新增一个只为了省掉几行前端 JSON 解析不值得）。执行时发现一个计划原文没写清楚、需要单独处理的前提：`upstream/narrative/` 只在 `TurnRunner`/`turn_finish` 每轮**开始/结束前**才会物化到工作区（`workspace/upstream.py` 模块顶部注释），项目从"叙事已定稿"状态第一次打开动画阶段、这个会话还没跑过一轮对话时，这个路径在文件树里根本不存在——不是"narrative.json 解析出 0 个镜头"，是"文件都没有"。`AnimationCanvas.vue` 据此加了 `narrativeMaterialized` 前置判断，没物化时不展示可能被误读成"这个项目真的没有镜头"的空列表，而是提示"请先在左侧发一条消息开始一轮"。这个状态在真实浏览器走查里被真实复现过一次（新建会话、发消息之前画布确实显示这条提示；发送消息、`TurnRunner` 跑完一轮后镜头列表才出现），不是凭代码推测出来的分支，见「验证记录」。
- 2026-09-29 — D38（T12）：镜头状态只计算"`animation/scenes/<id>.py` 是否存在"这一个信号，不做"已校验/已过期"——计划 T12 小节本身已经给出这条退路（"`validate_scenes` 的结果只存在于对话事件流里，不落库"），执行时复核确认这个前提成立：`agent/turn_events.py::handle` 把 `tool_result` 落库时只按 `turn_id`/`call_id` 存，没有为任何工具维护"按业务实体（这里是镜头 id）聚合的最近状态"的读模型。完整状态跟踪登记为新技术债 TD-33（`docs/quality/tech-debt.md`），留给以后真的需要时再做——大概率需要在落库 `tool_result` 时顺带抽取 `scene_id`（`validate_scenes`/`render_preview` 的入参或返回文本里已经点名了具体镜头），不是纯前端能解决的事。
- 2026-09-29 — D39（T12）：`KeyframeStrip.vue` 不拉取/显示真实缩略图，只给一句指向对话面板的静态提示——计划「下一步」把"关键帧展示要不要新端点"列为需要执行时判断的开放问题。读 `agent/turn_events.py::handle` 源码确认（第 60-73 行，`ToolResult` 分支的注释原文是"Image payloads are not persisted, only their types."）：`render_preview` 产生的 `ImageData.data_base64` 在落库/推送 `tool_result` 事件时被主动丢弃，只保留 `media_type`——这是 M1 就登记的技术债 TD-21，「来源」一栏原写"M2 处理"但没有钉死具体任务号。走查时真实调用了一次 `render_preview`（不是构造假数据，见「验证记录」），确认现象和代码分析一致：对话面板的工具结果卡片只显示"含 2 张图片（M1 未存图片内容，不可预览）"，没有任何图片字节可用。修 TD-21 需要改 `agent/turn_events.py` 的持久化格式（甚至要给图片内容找个存放的地方，例如 blob 库），这超出 T12"涉及文件"列声明的前端范围，属于 AGENTS.md 红线"不改变计划之外的公共接口"，本任务不顺带修。据此回答另一道开放问题——"前端画布是否需要单独重新拉取关键帧的按钮"：不需要，现有 `tool_result.images`（只有计数和类型）已经是能拿到的全部信息，加一条新端点也拿不到更多字节；`KeyframeStrip.vue` 只提示"在左侧对话里对镜头「id」调用 render_preview，结果会出现在对话的工具结果里"，指向 `SessionTimelineItem.vue`（M1 既有、T12 没有改动）已经在做的"含 N 张图片"计数展示。
- 2026-09-29 — D40（T12）：走查中发现并修复一个真实的响应式竞态 bug（不是纯文档层面的决策，记在这里是因为它改变了 `AnimationCanvas.vue::onSave` 的行为，值得和其它决策一起留痕）——原实现在 `writeMutation.mutateAsync` 成功后立刻把 `hadContent.value` 设成 `true`，但 `useWriteFileMutation` 的 `onSuccess` 只是让文件树查询失效，`sceneExists`（依赖这次失效后的重新拉取）真正变 `true` 之前有一段异步窗口。给一个"从没写过代码"的新镜头保存时，这段窗口里会短暂出现 `hadContent === true && sceneExists === false`，`fileMissing` 计算属性把这当成"曾经有内容、现在被删了"，触发 `computeMissingFileAction` 直接把刚保存、缓冲区已经干净的编辑器关掉——浏览器里真实复现过一次（保存后编辑器立刻跳回"从左侧选择一个镜头"，`s-hook` 状态却已经变成"已有代码"）。修复：`onSave()` 不再手动设置 `hadContent`，交给 `fileContent` 查询在 `sceneExists` 真正变 `true` 之后自然设置，消除这段竞态窗口；修复后重新走查确认编辑器保存后保留选中状态。这类"mutation 成功但依赖的查询失效还没跑完"的异步竞态是纯单测覆盖不到的（`conflictState.spec.ts`/`missingFile.spec.ts` 测的是纯函数，测不出触发条件本身错不错），是 SOP 要求"必须实际用浏览器走一遍"而不能只看单测通过的直接例证。
- 2026-09-29 — D41（T13）："渲染成片"按钮的禁用条件——T12 的决策记录 D38/技术债 TD-33 已经确认"已校验/已过期"这类状态不落库、前端拿不到，所以不做"上一次校验没通过就禁用"这种前端猜测。参照 D4"api 层是校验的唯一事实来源"的思路：`POST /render` 本身在动画阶段 `locked` 时会返回 4xx（`api/jobs.py::create_render_job_endpoint`），前端按钮只在两种前端自己就能确定、且确定禁用是合理的情况下禁用——"一个镜头都没有"（点了也没意义）和"已经有一个任务在 `queued`/`running`"（避免重复提交同一次渲染）；校验失败的 4xx 交给调用方（`FinalRenderPanel.vue::describeError`，复用 `AnimationCanvas.vue` 已有的 `ApiError` 处理模式）展示错误提示，不在前端重新发明一套判断规则，避免和 D4 产生两套不一致的规则。实现见 `frontend/src/features/canvas/animation/renderJobState.ts::isRenderButtonDisabled`。
- 2026-09-29 — D42（T13）：`FinalRenderPanel.vue` 用组件内部的 `currentJobId`（一个 `ref`）跟踪"当前正在看的渲染任务"，不做"刷新页面后自动恢复上一次任务的进度"——`api/jobs.py` 只有按 `job_id` 精确查询的端点，没有"查这个项目最近一次 `final_render` 任务"的端点，前端确实拿不到这个信息（不是偷懒没做，是当前后端能力做不到）。加一条端点属于"计划之外的公共接口"，不在 T13"涉及文件"列表内，登记为技术债 TD-34，留给以后真的需要"刷新后恢复进度"这个体验时再做。当前会话内点过一次"渲染成片"之后，进度/播放器/定稿都能正常工作，不影响 T13 完成标准要求的那条链路。
- 2026-09-29 — D43（T13）：L4 走查选择真实起 `python -m studio.worker` 进程（而不是像 T12 第 8 步那样手动构造/直接调用 `run_once`）来验证"渲染成片→完成→播放→定稿"整条链路——T4 的两镜头 fixture（`Dot()`/`Square()`，各 1.4s/1.6s 音频）渲染耗时只有几秒（worker 日志实测"镜头 s-explain 渲染完成（1.60s）"），真实排队等待的时间成本可以接受，比伪造 job 状态更能验证前端轮询（`jobRefetchIntervalMs`）和真实网络时序下的行为（例如 206 Partial Content 的 range 请求、真实的 `<video>` 加载/播放）。
- 2026-09-29 — D44（T14）：端到端测试驱动"agent 在一轮里调用工具"这一步时，用真实的 `TurnRunner.start_turn`/`wait`（替换 `app.state.runtime_factory` 里 `fake` 的注册为一个带明确脚本的 `FakeRuntime([write(...), write(...), call_tool("validate_scenes"), call_tool("render_preview", {...})])`），不是像 T7/T8 的单测那样直接手工构造 `ToolContext` 调 `invoke_tool`——T14"下一步"原文本身就要求验证"在一轮真实 turn 里调用"这条路径（`materialize_upstream` 在 `TurnRunner` 里于轮次开始时执行，`validate_scenes`/`render_preview` 依赖的 `upstream/narrative/` 必须先物化），只有走真实 `TurnRunner` 才能覆盖到这一层，复用 `tests/api/conftest.py::ApiEnv.make_busy` 已经示范过的"替换 fake 注册"手法。断言工具调用结果时，`agent/turn_events.py` 落库的 `tool_result` payload 只有 `call_id`（不含工具名，见 `turn_events.py:60-73`），测试里先用同一轮 `tool_call` 事件的 `{call_id: name}` 建一份映射，再按名字取对应的 `tool_result`，不依赖事件在列表里的顺序位置（顺序本身不是这条测试要验证的不变量，`event_asserts.py` 的既有设计哲学——只断言真正的因果关系——同样适用于这里，虽然本任务没有直接复用那个模块的函数）。
- 2026-09-29 — D45（代码评审）：独立评审（subagent，范围 `44e7dd3..4340e3a`）发现 `Project.completed_at` 在动画阶段被重新打开（`POST /stages/animation/reopen`，M1 就有的通用端点）后不会清空，导致成片已经不代表当前工作区、阶段状态已经变回 `active`，但前端仍显示"项目已完成"（Important，真实可达，T13 自己的走查记录里"重新打开"按钮确实会出现）。修复方式：`db/repo/projects.py` 新增 `clear_project_completed`（`mark_project_completed` 的反操作）；`api/projects.py::reopen_stage_endpoint` 只在 `stage == "animation"` 时调用它——刻意不改 `stage_flow.reopen()` 本身（那是和具体阶段无关的通用函数，"项目完成"是动画阶段特有的语义，`completed_at` 本来就是在 animation 专属的 `finalize_render_endpoint` 里设置的，不是在通用的 `finalize_stage_endpoint` 里，清空的地方对称地放在同一层）。新增测试见「验证记录」。评审同时指出一条 Minor（`POST /render` 不防重复排队），评估后判断修复成本大于收益（单 worker 顺序处理不会写坏文件，只白渲染一次），登记为 TD-35，不修。评审"declined to judge"列表里的其余条目（多进程队列并发、TD-32/33/34、`run_once` 的窄 TOCTOU 窗口、agent 代码经子进程执行属于产品设计本身、`async def` 路由同步 DB 调用）复核后同意不处理，理由已经是既有决策或明显超出本计划范围。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 2026-09-28（T2）：manim 的 `Scene.add_sound()` 会给整段视频的音轨套一层至少 1 秒的静音底轨（`pydub.AudioSegment.silent()` 不传参时默认 1000ms），即使所有镜头声明的音频时长加起来远小于 1 秒，容器时长也会被这条底轨拖到 ~1.0s+。单测里用的合成静音音频要 ≥ 1.0s 才不会踩到这个下限；真实叙事音频（旁白通常几秒）基本不会遇到。已写进 `docs/references/manim.md`（2026-09-28，实测）。
- 2026-09-28（T5）：本机 Homebrew 安装的 ffmpeg（8.0.1）编译时没有启用 libass/libfreetype，`drawtext`/`subtitles` 滤镜都不可用（`ffmpeg -filters` 输出里没有这两项），计划里"加字幕"最常见的两条实现路径都走不通。改用 Pillow 画字幕图 + `overlay` 滤镜叠加（决策记录 D17），已写进新建的 `docs/references/ffmpeg.md`（2026-09-28，实测）。
- 2026-09-28（T5）：D16 提到的副作用——worker 逐镜头单独渲染后，manim 音轨 1 秒静音下限（T2 已发现的行为）变成按每个镜头单独触发，不是像 T2 的 `render_preview` 那样看"目标镜头之前所有镜头的总时长"。M2 fixture 的两个镜头（1.4s/1.6s）都不低于 1 秒没有踩到，但这是"渲染出的镜头时长 = 声明的音频时长"这个不变量在 worker 场景下的新边界条件，已更新进 `docs/references/manim.md` 的"影响范围"一节（2026-09-28）。
- 2026-09-28（T6）：`SuggestionValue`/`JobValue` 这类只读值对象直接和"刚创建返回的对象"做完整 dataclass 相等比较时，`created_at` 会不一致——`Suggestion.created_at` 的默认值（`_utcnow()`）在 Python 侧是 aware datetime，但 SQLite 的 `DateTime(timezone=True)` 列重新查询后读出来的是 naive datetime（同一个时刻，`tzinfo` 不同）。写 repo 测试时不要对"刚创建的值对象"和"重新查询回来的值对象"做整体 `==`，按字段挑着断言（`jobs`/`snapshots` 的现有测试已经是这么写的，只是没人明确记录过原因）。这是 SQLite/SQLAlchemy 的已知限度，不是本计划引入的 bug，不需要改仓储代码。
- 2026-09-29（T9）：T9 计划正文和「下一步」两处都把"人工通读确认一致"的设计依据写成"§5.3、§8（风格组件经验）"，但设计文档 §8 实际是"测试策略"，和风格组件经验无关；"现有风格组件的编写经验写进动画阶段的提示词：必须有布局骨架、图标克制、转场不留中间态、避免角落堆放元素"这句话实际在 §5.5（提示词）。这是计划文本里的一处交叉引用笔误，不是设计文档本身自相矛盾（§5.5 的内容清楚、无歧义），所以不算 SOP §6 升级条件，本次顺手在通读时按 §5.5 的实际内容写了`prompt.md`"现有风格组件的编写经验"一节，不改设计文档，只在这里记录笔误供以后引用时留意。
- 2026-09-29（T7）：`backend/tests/stages/` 目录有 `__init__.py`（让 `stages` 成为一个正规 Python 包），`backend/tests/conftest.py`（顶层，定义 `AnimationProjectEnv`，D13）没有。`pytest` 收集测试时按"rootdir 插入"规则把 `backend/tests/`（第一个没有 `__init__.py` 的祖先目录）加进 `sys.path`，所以运行时 `from conftest import AnimationProjectEnv` 在 `tests/stages/` 下的文件里也能找到顶层那个 `conftest.py`。但 `pyright` 解析裸的非相对 import 时，会把"发起 import 的文件所在目录"当成一条隐式搜索路径（近似 Python 直接运行脚本时 `sys.path[0]` 是脚本自己所在目录的行为），且这条路径的优先级高于其它配置的根路径——`tests/stages/` 目录下正好也有一个 `conftest.py`（定义 `db_path`/`engine`/`migrated_engine`/`workdir` 等阶段测试用的 fixture，不含 `AnimationProjectEnv`），`pyright` 优先命中这个，报 `"AnimationProjectEnv" is unknown import symbol`（不是"模块找不到"，是"模块找到了但没有这个符号"，说明确实解析到了错的那个 `conftest.py`）。两个工具对同一条 `import conftest` 语句给出不同答案，是本任务实测发现的，此前 `tests/conftest.py` 的消费者（`test_worker.py`、`test_animation_fixture.py`）都直接在 `tests/` 顶层，没有暴露过这个问题。解决办法见决策记录 D25：用本地 `Protocol` 结构类型代替直接导入，测试子目录（带 `__init__.py`）里未来还会用到顶层 `conftest.py` 类型的文件都要用同样的办法。
- 2026-09-29（T12）：Browser pane 的 `preview_start`（按 `.claude/launch.json` 里相对路径 `cwd: "backend"`/`"frontend"` 起 `make dev` 对应的进程）在本 worktree 里把这个相对路径解析到了**主仓库** `/Users/peng/Me/Ai/ai-video-studio`，不是当前 worktree `/Users/peng/Me/Ai/ai-video-studio/.claude/worktrees/m2-animation`——实测：调用后 uvicorn 日志打印 `Will watch for changes in these directories: ['/Users/peng/Me/Ai/ai-video-studio/backend/src']`（少了 `.claude/worktrees/m2-animation` 这段前缀），随后用 `seed_animation_project` 建的项目在浏览器里访问 404（因为主仓库那份 `backend` 当时跑的不是 `m2-animation` 分支的代码，压根没有这次种下的数据，甚至可能没有 T1-T11 的改动）。用绝对路径改写 worktree 自己的 `.claude/launch.json` 之后重试，问题依旧——说明 Browser pane 工具实际读的是主仓库根目录下**另一份** `.claude/launch.json`（用 `Read` 工具确认过主仓库根目录下确实存在同样内容的文件），不是当前 worktree 里这份，且不能修改主仓库（红线）。绕过方法：不用 `preview_start`，改用 `Bash` 直接在 worktree 的绝对路径下起 `uv run uvicorn`/`pnpm run dev`（后台进程），再用 `navigate` 把 Browser pane 指到对应的 `localhost` 端口——`navigate` 只是打开一个 URL，不涉及 `.claude/launch.json` 解析，不受这个问题影响。走查开始时还发现端口 8000 被一个孤儿进程占用（`PPID 1`，从前一天 23:56 就在跑，响应真实的健康检查，判断是更早一个会话的 `uvicorn --reload` 子进程没有被正常回收），手动 `kill` 掉才能起新的。这条记在这里供以后在这个 worktree 里用 `make dev`/`preview_start` 走查的会话参考：**先用 `navigate` 而不是 `preview_start`，或者先确认 `preview_start` 启动后日志里的目录路径确实落在当前 worktree 下**，否则会在一个过期/错误的代码版本上走查而不自知。这是本地开发环境/工具的坑，不是产品代码问题，不登记进 `tech-debt.md`（那张表登记的是产品代码技术债）。
- 2026-09-29（T12）：本次走查通过 Browser pane 的 `computer`/`screenshot` 反复检查过界面（镜头列表状态、代码编辑器读写、"还没有物化"提示、`KeyframeStrip` 提示文案、对话面板里 `validate_scenes`/`render_preview` 结果卡片），但当前会话可用的工具集里没有一个能把这些截图落地成 `data/evidence/m2-animation/*.png` 文件——`computer` 的 `screenshot`/`zoom` 只把图片内容回传进对话供当场查看，没有"保存到磁盘"的参数或返回路径，也没找到其它能导出浏览器截图的工具。「验证记录」因此改成写清楚每一步的可复现操作，并且大量使用 `javascript_tool` 读取真实 DOM 文本（`document.querySelector('.cm-content')?.innerText` 之类）作为比截图更精确、不依赖人工转录的证据——没有 PNG 文件产出。这是本次执行环境的工具限制，不是回避走查：该做的浏览器操作、该触发的真实后端调用都做了，只是没有留下图片文件；如果以后的会话在这个环境里拿到了能保存截图的工具，可以补拍。
- 2026-09-29（T11）：「下一步」原文写"读 `output/final.json` 走 `workspace.files.read_text`"，实测这条路径走不通：`workspace/layout.py` 把 `output` 列进 `EXCLUDED_TOP_DIRS`（第 13 行），`HIDDEN_TOP_DIRS = EXCLUDED_TOP_DIRS - {"upstream"}`（第 15 行）也包含 `output`；`workspace/files.py::read_text` 对落在 `HIDDEN_TOP_DIRS` 下的路径会主动抛 `ScopeError("路径不可读：...")`（`files.py:113-117`），用 `uv run python -c "..."` 直接调用验证过确实抛错，不是读到空内容或别的静默失败。这不是设计文档或计划本身自相矛盾（`output/` 对 agent/前端隐藏这条规则在 T1/T4 之前就有，`read_text` 只是忠实执行了这条规则），只是"下一步"里给的落地提示和这条既有规则冲突，按决策记录 D32 改成直接用 `pathlib` 读（T10 的下载端点已经是这么处理 `output/final.mp4` 的，不是新模式）。记在这里供以后有人想在 api 层读 `output/`/`.cache/` 下的文件时，别再想着走 `workspace.files.*` 这条路。
- 2026-09-29（T13）：前端 `types/api.ts::ProjectOut` 此前一直没有 `completed_at` 字段——T11（2026-09-29 早些时候）已经给后端 `api/schemas.py::ProjectOut` 加了这个字段（决策记录 D35），但当时没有同步更新前端类型（T11"涉及文件"列表本来就没有前端），T12 也没碰到（T12 不需要读这个字段）。T13 因为"成片定稿后顺手展示项目已完成"这个需求第一次要读它，才发现前端类型和后端响应实际字段不一致——`request<T>()` 是无运行时校验的 `JSON.parse(text) as T` 强转，字段缺失在类型层面不会报错，只会在真正用到那个字段时才发现"类型上有，其实一直没告诉 TS"（这次反过来，是"后端有、前端类型没声明"，同一类风险）。已在 T13 里补上；记在这里提醒以后新增后端响应字段时，同一个任务里顺手检查一下前端 `types/api.ts` 是否需要同步，不要假设"没人用就不用补"。

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
- AC5（2026-09-28，L2）：`pytest backend/tests/db/test_repo_suggestions.py backend/tests/stages/test_common.py` → `7 passed`：`test_create_suggestion_defaults_to_open_status` 断言新建记录 `status == "open"` 且字段齐全；`test_list_suggestions_filters_by_project_and_status` 断言按 `project_id`/`status` 过滤；`test_update_suggestion_status_changes_status_and_persists` 断言状态变更落库。`tests/stages/test_common.py::test_calling_tool_creates_open_suggestion` 直接构造 `ToolContext` 调 `invoke_tool(build_suggest_upstream_change_tool(engine), ctx, {...})`，断言 `suggestions` 表新增一条 `from_stage="animation"`/`status="open"` 的记录；`test_tool_is_scoped_to_animation_stage` 断言 `spec.stages == {"animation"}`；`test_invalid_args_do_not_write_a_suggestion` 断言参数校验失败时不写库。`make check` 全绿（后端 643 passed / 17 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- T7（2026-09-29，L2；不是独立 AC——是 AC4 端到端链路的一环，要等 T14 才勾）：`pytest backend/tests/stages/test_animation_validate.py` → `5 passed, 1 deselected`；`pytest backend/tests/stages/test_animation_validate.py -m slow` → `1 passed`。6 个用例覆盖：`test_tool_is_scoped_to_animation_stage`（`spec.stages == {"animation"}`）；`test_all_valid_scenes_pass`（`@pytest.mark.slow`，两个镜头都写合法 manim 代码，断言 `is_error is False`、文本含"2"和"通过"）；`test_missing_scene_file_is_reported_by_scene_id`（只写 `s-hook.py`，断言 `is_error is True`、文本含 `"s-explain"` 不含 `"s-hook"`）；`test_empty_scene_file_is_treated_as_missing`（`s-explain.py` 内容是空白字符）；`test_syntax_error_is_reported_by_scene_id`（`s-explain` 代码 `"x = [1, 2\nself.wait(1)"`，断言文本含 `"s-explain"`、`"SyntaxError"`，不含 `"s-hook"`——验证 `_relabel_scene_errors` 正确换算了 `_static_check` 产出的 `"scene 1: SyntaxError..."`）；`test_narrative_json_missing_is_a_tool_error`（`upstream/narrative/narrative.json` 不存在时，`invoke_tool` 兜底把 `FileNotFoundError` 转成 `is_error=True` 的 `ToolResult`，文本含"工具执行出错"）。`make check` 全绿（后端 648 passed / 18 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- T8（2026-09-29，L2；不是独立 AC——是 AC4 端到端链路的一环，要等 T14 才勾）：`pytest backend/tests/stages/test_animation_preview.py` → `4 passed, 1 deselected`；`pytest backend/tests/stages/test_animation_preview.py -m slow` → `1 passed`。5 个用例覆盖：`test_tool_is_scoped_to_animation_stage`（`spec.stages == {"animation"}`）；`test_render_preview_returns_one_image_per_beat_and_deviation_text`（`@pytest.mark.slow`，对 `s-explain` 调工具，断言 `is_error is False`、`len(images) == 2`（fixture 里 `s-explain` 有 2 个 beat）、每张图 `media_type == "image/png"` 且 `data_base64` 非空、文本含 `"s-explain"` 和"偏差"）；`test_unknown_scene_id_is_a_tool_error`（`scene_id="s-nonexistent"`，断言 `is_error is True`、文本含 `"s-nonexistent"`）；`test_missing_scene_code_is_reported_by_scene_id`（`s-explain.py` 不写，断言 `is_error is True`、文本含 `"s-explain"`）；`test_engine_timeout_becomes_tool_error`（`monkeypatch.setattr(ManimRenderEngine, "render_preview", ...)` 换成直接返回 `success=False, error_message="预览渲染超时"` 的假实现，断言工具原样转成 `is_error=True`、`text == "预览渲染超时"`、`images == []`，不真的等一次超时渲染——引擎层的超时行为已由 T2 覆盖，见决策记录 D26）。额外单独跑 `pytest backend/tests/stages -m slow` → `2 passed`（T7 的 `test_all_valid_scenes_pass` + T8 的端到端渲染用例一起跑，互不干扰）。`make check` 全绿（后端 652 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。
- T9（2026-09-29，L2；不是独立 AC——系统提示词质量不是任何 AC 的直接验证对象，但支撑 AC4 端到端链路里 agent 能写出可校验通过的代码这件事）：`pytest backend/tests/stages/test_animation_prompt.py` → `8 passed`：`test_system_prompt_embeds_element_exit_rules_verbatim`（`rules.ELEMENT_EXIT_RULES.strip()` 逐字出现在 `system_prompt()` 里）、`test_system_prompt_mentions_element_exit_keyword`/`_validate_scenes_tool`/`_render_preview_tool`/`_scene_merge_convention`/`_manim_version`/`_style_component_experience`（分别断言"画面不重叠"/`validate_scenes`/`render_preview`/`Scene`+"合并"/"Manim Community v0.20.1"/"布局骨架""图标克制""转场不留中间态""角落堆放"）、`test_element_exit_rules_constant_is_non_empty`（`rules.py` 本身的单测）。**人工通读一遍 `prompt.md` 全文的结论**：内容和设计 §5.3（`validate_scenes`/`render_preview` 的角色、"各镜头代码合并到同一个 Scene 类"约定、120 秒超时提示）以及 §5.5（`ELEMENT_EXIT_RULES` 原文、风格组件四条经验）的意图一致；"镜头代码合并约定"一节里关于自动跨镜头变量提升/`clear_except`/自动补齐 `self.wait` 的描述逐条对照了 `engines/render/manim/{script,engine}.py` 的现有实现，没有凭空写引擎不支持的行为；`rate_func` 一节按 `_RateFuncRewriter` 的实际行为改写了旧文档的表述（旧文档要求手写 `rate_functions.` 前缀，新引擎会自动补，所以改成"不需要手写前缀"）；通读时发现并移除了草稿里对 `suggest_upstream_change` 的调用提示（决策记录 D28，工具实际未接入 `tools()`）；也发现计划正文对设计依据的引用"§8（风格组件经验）"是笔误（应为 §5.5），记入「意外与发现」，未改动设计文档本身。`make check` 全绿（后端 660 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。T9 不涉及 manim/ffmpeg 子进程，未额外跑 `-m slow`。
- T10（2026-09-29，L2；不是独立 AC——api 端点本身不是任何 AC 的直接验证对象，但是 AC4 端到端链路"点击渲染成片"这一步的支撑，要等 T14 才勾）：`pytest backend/tests/api/test_jobs.py` → `9 passed`。三组用例：`TestCreateRenderJob`（`test_creates_queued_job_for_active_animation_stage` 用 `seed_animation_project` 建一个动画阶段 `active` 的项目，断言 `POST .../render` 返回 201、`status="queued"`、`progress==0.0`、`error is None`；`test_locked_animation_stage_is_4xx` 用刚创建的项目（动画阶段默认 `locked`）断言返回 4xx；`test_unknown_project_is_404`）、`TestGetJob`（能查到刚创建的 `queued` 任务；未知任务 404；另一个项目的任务 404，验证不会跨项目泄露）、`TestDownloadFinalVideo`（手动往 `api_env.workdir(pid)/output/final.mp4` 写字节，下载端点 200 且 `Content-Type: video/mp4`、内容一致；成片不存在时 404；未知项目 404）。`make check` 全绿（后端 669 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。T10 不涉及 manim/ffmpeg/worker 子进程或真实渲染，未额外跑 `-m slow`。
- AC4 部分收尾（T11，2026-09-29，L2；仍不是独立 AC——完整的 AC4 端到端链路要等 T14 才勾，但"成片定稿"这一步本身已经有完整测试证据）：先跑 `pytest tests/api/test_animation_finalize.py -q` 确认在实现之前 4 个用例里 2 个因路由不存在而 404 失败（先红），实现后 `4 passed`：`test_missing_final_json_is_4xx`（还没渲染过，404）；`test_stale_snapshot_is_4xx`（用 `latest_snapshot` 取渲染时的快照写进 `final.json`，再手动写一个镜头文件并 `create_snapshot` 制造"渲染后又有改动"，409，`detail` 含"重新渲染"）；`test_matching_snapshot_finalizes_stage_and_completes_project`（`final.json` 记录的快照和当前最新快照一致，200，`status=="finalized"`、`finalized_snapshot_id` 等于该快照 id，再 `GET /api/projects/{id}` 确认 `completed_at` 非空）；`test_unknown_project_is_404`。`backend/tests/db/test_migrate.py` 新增 `test_migrate_adds_projects_completed_at_column`，`pytest tests/db/test_migrate.py -q` → `5 passed`（含原有 4 条），确认新迁移 `0003_projects_completed_at.py` 在 `migrate()` 程序化调用 `alembic upgrade head` 时正常生效（本项目没有独立的 `alembic.ini`/CLI 入口，`studio.db.engine.migrate()` 复用调用方连接程序化执行，这就是"alembic 检查"在这个项目里的实际形式，见 `db/engine.py:56-65`）。`make check` 全绿（后端 674 passed / 19 deselected，前端 128 passed，import-linter 21 kept，pyright 0 errors）。T11 不涉及 manim/ffmpeg/worker 子进程或真实渲染，未额外跑 `-m slow`。
- T12（2026-09-29，L4；不是独立 AC——AC6 要等 T13 把成片面板也做完才勾，但"镜头列表/代码编辑器/关键帧展示"这部分已经有完整走查证据）：
  - 单测：`pnpm --dir frontend test` → `21 files / 151 passed`（比 T11 时的 128 多 23 个：`narrativeScenes.spec.ts` 5、`sceneStatus.spec.ts` 3、`keyframeHint.spec.ts` 2、`conflictState.spec.ts`（animation 版）9、`missingFile.spec.ts`（animation 版）3、外加 `fileKind.spec.ts` 沿用未变）；`pnpm --dir frontend lint`、`pnpm --dir frontend typecheck` 均无输出（通过）。
  - L4 浏览器走查（未能保存 PNG 截图，见「意外与发现」；以下是实际操作序列和用 `javascript_tool`/`read_network_requests`/后端日志核实过的真实结果，不是推测）：
    1. 用绝对路径直接 `uv run uvicorn studio.main:app --reload --reload-dir src --host 127.0.0.1 --port 8000`（`STUDIO_ENABLE_FAKE_RUNTIME=true`）+ `pnpm run dev` 在 worktree 目录下起两个进程（绕开 `preview_start` 解析到主仓库的问题，见「意外与发现」），确认 uvicorn 日志里 `Will watch for changes in these directories` 指向的是本 worktree 路径。
    2. 用 `backend/tests/fixtures/animation/seed.py::seed_animation_project`（连到 `make dev` 同一个 `data/studio.db`/`data/blobs/`）种出项目 `00d4ba96d009478a83122ca2bbc9bcbb`（"叙事已定稿"状态，动画阶段 `active`）。
    3. 浏览器打开 `http://localhost:5173/projects/00d4ba96d009478a83122ca2bbc9bcbb/animation`：阶段导航显示"选题✓ — 叙事✓ — 动画"，画布区域显示"还没有镜头列表：`upstream/narrative/` 要在这个会话跑过第一轮对话后才会物化。请先在左侧发一条消息开始一轮。"（D37 的判断在真实环境下成立）。
    4. 选模型配置为 `fake`、新建会话、发送一条消息（"开始写动画镜头"）；`write_file` 工具调用 `Completed`，快照创建；画布区域自动变成镜头列表：`s-hook`（待编写）、`s-explain`（待编写），顺序与 fixture 的 `narrative.json` 一致。
    5. 点击 `s-hook`：右侧出现空的 CodeMirror 编辑器（Python 语言包生效，语法高亮可见）+ 提示"这个镜头还没有代码，写完后保存即可创建 `animation/scenes/s-hook.py`" + 下方 `KeyframeStrip` 提示"在左侧对话里让 agent 对镜头「s-hook」调用 render_preview 工具：……当前版本图片内容还没有持久化（技术债 TD-21），这里和对话里都只能看到数量，看不到缩略图。"；键入 `self.add(Dot())`（用 `document.querySelector('.cm-content')?.innerText` 核实过每一步键入后的真实内容，排除了一次因为自动补全/焦点问题漏掉"self."前缀的假阳性）；点击保存后 `s-hook` 变成"已有代码"（绿色）——**这一步复现了 D40 的 bug**：保存瞬间编辑器被错误关闭回"从左侧选择一个镜头"，确认是 `hadContent`/`sceneExists` 的竞态后修复（去掉 `onSave` 里手动设置 `hadContent`），HMR 热更新后重新走查确认编辑器保存后正确保留选中状态、内容不丢。
    6. 用同样的方式给 `s-explain` 写入 `self.add(Square())` 并保存，两个镜头都变成"已有代码"。
    7. 刷新整个页面（新的一次 `navigate`）：session 选择器自动恢复到之前的会话，镜头列表仍显示两个"已有代码"，点开 `s-hook` 内容仍是 `self.add(Dot())`（验证保存真正落了工作区文件，不是只存在内存里）。
    8. 用一个独立脚本（`ToolContext` 手工构造，直接 `invoke_tool(VALIDATE_SCENES_TOOL, ctx, {})` 和 `invoke_tool(RENDER_PREVIEW_TOOL, ctx, {"scene_id": "s-explain"})`，不是构造假数据）对刚才种的项目真实跑了一次 `validate_scenes`（结果：`is_error=False`，"全部 2 个镜头静态校验通过"）和一次 `render_preview`（真实起了一次 manim 渲染 + ffmpeg 抽帧，结果：`is_error=False`，2 张关键帧，文本"镜头 s-explain 预览渲染完成：渲染时长 2.44s，配音时长 1.60s，偏差 0.00s。"），并把这两个调用按 `agent/turn_events.py::handle` 落库 `tool_call`/`tool_result` 事件的同样格式（含"图片只存 `media_type`"这条 TD-21 规则）追加进已有那一轮的 `turn_events`，模拟"agent 在这一轮里调用了这两个工具"。刷新会话后，对话面板里正确出现 `validate_scenes`（Completed）和 `render_preview`（Completed，展开后 `PARAMETERS: {"scene_id": "s-explain"}`，`RESULT` 显示"镜头 s-explain 预览渲染完成：渲染时长……"，下方"含 2 张图片（M1 未存图片内容，不可预览）"）——这正是 D39 判断的"关键帧只能看到数量提示"在真实环境下的样子，`SessionTimelineItem.vue`（M1 既有、T12 未改动）的既有渲染逻辑和 T12 新写的 `KeyframeStrip.vue` 提示文案口径一致。
    9. 走查结束后 `kill` 掉手动起的 uvicorn（含 reload 子进程）和 vite 进程，`lsof -nP -iTCP:8000 -sTCP:LISTEN`/`:5173` 确认端口已释放；关闭 Browser pane 的最后一个 tab。
  - `make check` 全绿（后端 674 passed / 19 deselected，前端 21 files / 151 passed，import-linter 21 kept，pyright 0 errors）——backend 未改动，数字和 T11 完全一致；frontend 数字见上。
- AC6 收尾（T13，2026-09-29，L4；AC6 从这里正式打勾）：
  - 单测：`pnpm --dir frontend test` → `22 files / 165 passed`（比 T12 时的 151 多 14 个：`renderJobState.spec.ts` 5 条 + `queries.spec.ts`/`endpoints.spec.ts` 各新增若干条）；`pnpm --dir frontend lint`、`pnpm --dir frontend typecheck` 均无输出（通过）。`make check` 全绿（后端 674 passed / 19 deselected 不变，前端见上，import-linter 21 kept，pyright/vue-tsc 0 errors）。
  - L4 浏览器走查（真实起 api + worker + frontend 三个进程，绕开 T12 记录的 `preview_start` 坑；未能保存 PNG 截图，见「意外与发现」，以下是实际操作序列和用 `javascript_tool`/`read_network_requests`/后端 worker 日志/`curl` 核实过的真实结果）：
    1. `STUDIO_ENABLE_FAKE_RUNTIME=true uv run uvicorn studio.main:app --reload --reload-dir src --host 127.0.0.1 --port 8000`、`uv run python -m studio.worker`、`pnpm run dev` 三个进程都在 worktree 目录下起（`Will watch for changes in these directories` 指向本 worktree 路径，`[worker] 已启动，轮询间隔 2.0s`）。
    2. 用 `seed_animation_project`（连到同一个 `data/studio.db`/`data/blobs/`）种出项目 `bf2619d253c445e0ab20d6da4c24c6f6`。
    3. 浏览器打开 `.../animation`：画布提示"还没有镜头列表……请先在左侧发一条消息开始一轮"（同 T12 的 D37 现象）。选模型配置为 `fake`、新建会话 `deb3dae4`、发送"开始写动画镜头"；`write_file` 工具调用 `Completed`，快照创建；镜头列表出现 `s-hook`/`s-explain`（均"待编写"），下方出现新的"成片"区块，"渲染成片"按钮可点（`sceneCount` 此时为 2）。
    4. 依次点开 `s-hook`/`s-explain`，编辑器输入 `self.add(Dot())`/`self.add(Square())`（`document.querySelector('.cm-content')?.innerText` 核实内容），点击"保存"——两次都一次成功变成"已有代码"，没有复现 T12 记录的 D40 竞态（D40 已在 T12 修复）。
    5. 点击"渲染成片"：按钮立即变灰禁用（`isRenderButtonDisabled` 生效），状态文案显示"排队中"（`jobStatusLabel('queued')`）。
    6. 约几秒后 worker 日志出现 `[worker] 镜头 s-hook 渲染完成`/`[worker] 镜头 s-explain 渲染完成（1.60s）`/`[worker] 任务 337e10cddf684efa8e1f0fda8eb8f6f1 完成`；前端面板（1 秒轮询，`jobRefetchIntervalMs`）自动追到 `done`：进度条填满、状态文案"已完成"、`<video>` 元素出现。`read_network_requests` 确认 `GET .../output/final.mp4` → `206 Partial Content`。点击播放后用 `javascript_tool` 读 `video` 元素属性：`{currentTime: 3.029362, duration: 3.029362, paused: true, ended: true, readyState: 4}`——真实播放到底，不是空播放器。
    7. 点击"成片定稿"：`read_network_requests` 确认 `POST .../animation/finalize-render` → `200 OK`；阶段导航从"动画"变"动画✓"，右上角按钮从"定稿"变"重新打开"，面板标题栏出现"项目已完成"（`project.completed_at` 非空触发）。`curl http://localhost:8000/api/projects/bf2619d253c445e0ab20d6da4c24c6f6` 确认响应体 `completed_at: "2026-09-28T20:10:54.294314"`。
    8. 走查结束后 `pkill` 掉 uvicorn（含 reload 子进程）、worker、vite 三个进程，`lsof -nP -iTCP:8000 -sTCP:LISTEN`/`:5173` 确认端口已释放；关闭 Browser pane 的最后一个 tab。
  - 完整复现了 T13 完成标准的四步：点击渲染成片 → 看到进度变化（排队中→已完成，进度条填满）→ 完成后能播放（真实播放到 `ended:true`）→ 点击成片定稿后阶段状态变化（动画✓、"重新打开"、"项目已完成"）。AC6 原文"前端动画画布能显示镜头列表、代码编辑器、预览关键帧和渲染成片进度/播放器"——T12 覆盖了前三项（镜头列表/代码编辑器/预览关键帧提示），本次 T13 覆盖了最后一项（渲染成片进度/播放器），AC6 在此打勾。
- AC4/AC7 收尾（T14，2026-09-29，L2；AC4 从这里正式打勾，AC7 靠 `make check` 持续保持绿在这里正式打勾）：新建 `backend/tests/api/test_animation_flow.py::TestAnimationEndToEndFlow::test_narrative_to_finalized_render`（`@pytest.mark.slow`），串起完整链路：
  1. `seed_animation_project` 种出"叙事已定稿"项目（动画阶段 `active`）。
  2. 用真实 `app.state.turn_runner.start_turn`/`wait` 跑一轮 animation 阶段的 turn（`model_profile="fake"`，把 `runtime_factory` 的 `fake` 注册替换成一个带明确脚本的 `FakeRuntime`）：脚本依次 `write("animation/scenes/s-hook.py", "self.add(Dot())")`、`write("animation/scenes/s-explain.py", "self.add(Square())")`、`call_tool("validate_scenes")`、`call_tool("render_preview", {"scene_id": "s-explain"})`。断言 `turn.status == "done"`；从 `list_events` 里按 `tool_call`/`tool_result` 的 `call_id` 配对，`validate_scenes` 的结果 `is_error is False` 且文本含"全部 2 个镜头静态校验通过"，`render_preview` 的结果 `is_error is False`、文本含 `"s-explain"`、`len(images) == 2`（该镜头 2 个 beat）——这一步验证的是"在一轮真实 turn 里调用"这两个工具没有问题（工具本身的正确性已由 T7/T8 独立测试覆盖），同时也是"手工叙事 fixture 解锁动画阶段"这条 M2 范围核心假设的端到端证据。
  3. `POST /api/projects/{id}/render` → 201；直接调用 `worker.run_once(engine, blobs, data_dir=...)`（不起真实进程）→ `claimed is True`；`GET /api/projects/{id}/jobs/{job_id}` → `status == "done"`；确认 `output/final.mp4`（非空）、`output/final.json` 都已写入工作区；`GET /api/projects/{id}/output/final.mp4` → 200，`Content-Type: video/mp4`。
  4. `POST /api/projects/{id}/animation/finalize-render` → 200，`status == "finalized"`，`finalized_snapshot_id` 非空；`GET /api/projects/{id}` → `completed_at` 非空。
  `pytest backend/tests/api/test_animation_flow.py -m slow` → `1 passed`（默认不带 `-m slow` 时按 `slow` marker 约定正确 deselected，不会拖慢 `make check`）。`pytest backend/tests -m slow` → `14 passed`（T1/T2/T5/T7/T8 已有的慢测试 + 本条，互不干扰，回归无破坏）。`test_manim_engine.py` 补了一句引用说明（指向 T2 的关键帧测试和本条端到端测试），未重复实现。复核设计 §9 风险表：R1–R5 标注"M1 完成"，本任务执行过程中没有触发任何一条、也没有发现新的风险假设不成立，不需要走 SOP §6 升级流程。`make check` 全绿（后端 674 passed / 20 deselected——比 T13 的 19 多 1，正是新增的这条端到端测试被 deselect；前端 22 files / 165 passed 不变，import-linter 21 kept，pyright/vue-tsc 0 errors）。至此本计划全部验收标准（AC1–AC7）都已打勾。
- 代码评审发现修复（2026-09-29，L2；决策记录 D45）：独立 subagent 评审时自己跑了一遍 `make check`（674 passed / 20 deselected）和 `pytest backend/tests -m slow`（14 passed），和上面 T14 记录的数字完全一致，确认评审基于的是真实结果而不是转述。评审发现的 Important 问题（`reopen` 动画阶段不清 `completed_at`）已修复：新增 `backend/tests/api/test_animation_finalize.py::TestFinalizeRender::test_reopening_animation_after_finalize_clears_completed_at`（先跑一次确认因 `clear_project_completed` 不存在而红，实现后绿），断言定稿后 `completed_at` 非空，调用 `POST /stages/animation/reopen` 后阶段回到 `active` 且 `completed_at` 变回 `None`。修复后完整跑一次 `make check`，全绿（后端 675 passed / 20 deselected——比修复前多 1，正是这条新测试；前端 22 files / 165 passed 不变，import-linter 21 kept，pyright/vue-tsc 0 errors）。Minor 问题（重复排队渲染任务）评估后登记为 TD-35，不修，理由见决策记录 D45 和 `docs/quality/tech-debt.md`。
