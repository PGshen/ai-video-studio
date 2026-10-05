# html-engine-2b：成片、预览与前端画布（多形态视频 子项目 2B）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成（2026-10-05 验收，已合并 main） |
| 里程碑 | 多形态视频流水线 · 子项目 2/4 · 计划 2B |
| 设计依据 | [子项目 2 设计](../../design/2026-10-04-timeline-html-engine.md)（已批准）§5.5、§6.3（`scene_checks` 衔接）、§7、§8、§9；[总设计](../../design/2026-10-04-html-video-pipeline.md)；[计划 2A](../completed/html-engine-2a.md)（已完成，已合并 main） |
| 分支 | `html-engine-2b` |
| 批准记录 | 2026-10-05：负责人验收 2A，要求写完 2B 计划后直接实现，不必等待计划审批；沿用 Native（内联）执行 + 最后一次整分支评审 |

> 执行者：按 superpowers:executing-plans 逐个任务执行；本计划的「进度」「决策记录」就是账本。每个任务先写失败的测试，再实现。计划只写结构和意图，不写完整实现代码。

## 目标

"知识讲解（HTML）"项目走完最后一段：前端有专属的动画画布（镜头 / 实时预览 / 成片三个标签），worker 能把 `animation/scenes/*.js` 渲染成带旁白的 `output/final.mp4`，成片定稿后项目完成。Manim 路径和老项目的行为、测试保持不变。

## 范围

**包含：**

- `engines.render.mix`（纯能力层）：按时间轴起点拼旁白轨、AAC、`+faststart`，时长以时间轴为准；接口预留背景乐轨。
- `engines.render.html.video`：逐帧出图、经管道交给 ffmpeg，输出无声 MP4，带进度回调。
- worker 分流：`final_render` 按项目 `settings.engine` 走 Manim 或 HTML；HTML 路径含前置检查、画面缓存、混音、`final.json` 新字段。
- api：`create_render_job`、`finalize-render` 按项目流水线解析实际的动画阶段；`scene_checks` 泛化到两组工具；预览端点（页面、资源、`meta`）。
- 前端：`useScenePlayback` 搬到 `composables/`；`CodeEditor` 支持 javascript；`HtmlAnimationCanvas`（含实时预览、传输控制）；`ProjectWorkbenchPage` 按阶段 key 分发。
- 测试、文档同步、测速与恢复实测、L4。

**不包含：**

- 配乐、节拍网格、短片与 MV；上游时间轴变化摘要；项目级分辨率与 fps（沿用 1920×1080、30fps）。
- 通用画布的 svg 之外的语法高亮；Manim 画布的任何改动。
- TD-69 中 ①②③④（静态检查词法、符号链接、末尾 beat、派生文件只读）。

## 全局约束

- 画布 1920×1080、30fps；帧数 `ceil(duration × fps)`；第 i 帧取时刻 `i / fps`。成片时长以时间轴 `duration` 为准（混音时 `-t duration`）。
- 成片不叠字幕（ADR 0016）。成片不缓存音频：缓存只含无声视频，混音每次重做。
- 画面缓存键：引擎版本、场景源码、`lib`、`global`、`assets` 的哈希、`timeline_hash`、分辨率与 fps（同 `page_hash` 再加 `timeline_hash`/分辨率/fps/引擎版本）；缓存目录沿用 `.cache/render_cache/`，`.mp4.tmp` 写完原子改名。
- worker：不依赖 `agent`/`stages`/`api`/`main`；可以依赖 `timeline`、`engines.render.html`、`engines.render.mix`、`db.repo`。`engines.render.html` 与 `engines.render.mix` 不 import `studio.timeline`，接收 dict 或数据类。worker 每个任务单独启动浏览器，结束即关。
- 进度回调同时更新 `progress` 与心跳（`update_progress` 不续心跳）；心跳间隔不超过 15 秒（沿用 worker 常量）。
- 预览端点：`Cache-Control: no-store`（不开 CORS，见决策记录）；iframe `sandbox="allow-scripts"`、不带 `allow-same-origin`；路径走 `workspace.safe_path`，拒绝越界；预览页追加的脚本只在预览模式出现，导出不含。
- 预览端点的页面与 `meta` 用工作区当前内容，不要求先拍快照；时间轴来自工作区顶层 `narrative/{narrative,timing}.json`（与 worker 同一来源，见决策记录）；上游缺失或不一致返回 409 加原因。
- 前端 `features/*` 之间不许互相 import；跨 feature 复用的放 `components/` 或 `composables/`。新增前端依赖仅 `@codemirror/lang-javascript`（本计划批准）。
- 老项目与 Manim 项目：`animation` 阶段、`validate_scenes`/`render_preview` 的行为与持久化格式完全不变。
- 测试标记：需要真实 Chromium 或 ffmpeg 的测试标 `slow`，用 `-m slow`，不进 `make check`。
- 新增后端依赖：无。ffmpeg 沿用系统二进制（Manim 路径已依赖）。

## 评审重点

规格隐含、但最容易在实际使用中出问题的情况（每条在对应任务里有测试）：

1. **成片读到的镜头与时间轴不一致**（缺镜头文件、镜头为空、静态检查有错、timing 与 narrative 不一致、音频文件缺失）：任务失败并点名镜头和原因，不留下半份成片，也不污染缓存（T3）。
2. **渲染中途的失败**（某一帧场景抛错、浏览器崩溃、ffmpeg 提前退出）：错误信息带镜头 id、时刻与堆栈或 ffmpeg 末尾日志；管道和浏览器被清理，`output/final.mp4` 不被半成品覆盖（T2、T3）。
3. **旁白轨道**：镜头时长与音频实际长度不一致（音频长于或短于镜头）、音频起点来自时间轴而不是文件顺序；混音后总时长等于时间轴时长（T1）。
4. **定稿的阶段名**：`explainer_html` 项目的 `finalize-render` 和 `render` 作用在 `animation_html`；老项目仍是 `animation`；渲染之后工作区又有改动时仍拒绝定稿（T4）。
5. **预览端点的安全与新鲜度**：`../` 与编码后的 `..%2f` 越界、符号链接、`scripts/` 里不存在的名字；工作区变化后 `meta.hash` 变、页面内容随之变；上游缺失给 409 而不是 500（T5）。
6. **预览播放时钟**：镜头切换时的音频与画面对齐、某个镜头没有配音时回退计时、iframe 报错不阻断编辑与成片、收到不是本 iframe 发来的消息被忽略（T6、T7）。

## 验收标准

- [x] AC1：`engines.render.mix` 按时间轴起点拼出旁白轨，总时长等于时间轴时长，音轨为 AAC、容器 `faststart`（验证方式：`-m slow` 的 `tests/engines/test_mix.py` + ffprobe）
- [x] AC2：`engines.render.html.video` 在真实 Chromium 下输出 30 帧级别的无声 MP4，帧数与时长正确，进度回调单调，失败时点名时刻并清理（验证方式：`-m slow` 的 `tests/engines/test_html_video.py`；纯逻辑部分的单测）
- [x] AC3：worker 对 `engine=html` 项目渲染出 `output/final.mp4` 与带 `engine`、`timeline_hash`、`audio_sources` 的 `final.json`；命中缓存时不再出帧；Manim 项目的现有测试不变（验证方式：`tests/test_worker.py` 新增用例；`-m slow` 端到端）
- [x] AC4：`render` 与 `finalize-render` 按项目流水线解析动画阶段；`scene-checks` 对 `animation_html` 的两个工具生效且输出形状与 Manim 一致（验证方式：`tests/api/`）
- [x] AC5：预览端点（页面、资源、`meta`）符合设计 §7.1，含 `no-store`、路径越界拒绝、409（验证方式：`tests/api/test_html_preview.py`）
- [x] AC6：前端传输时钟、镜头刻度、iframe 消息协议的纯函数有单测；`HtmlAnimationCanvas` 三个标签有组件测试；`useScenePlayback` 搬迁后行为不变（验证方式：vitest；`make check`）
- [x] AC7（成片音画偏差已用点击音轨加白闪实测为 0 毫秒，预览偏差只做了推算，见 references）：L4：在内置浏览器里，用种子脚本写入镜头，实时预览可播放、拖动进度条、循环镜头；成片标签能触发渲染、播放成片并定稿；预览与成片的音画偏差已对比并记录（验证方式：控制者截图与数据）
- [x] AC8：测速与恢复实测写入 references：出帧速度与长视频时长、浏览器池真实 SIGKILL 后的恢复、常驻浏览器的内存占用（验证方式：`docs/references/html-video-render.md`，`-m slow` 的恢复用例）
- [x] AC9：`ARCHITECTURE.md`、`QUALITY.md`、`docs/runbooks/verification.md`、`tech-debt.md`（TD-69 ⑤ 结论）、`docs/plans/TODO.md` 已同步；`make check` 为绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->
<!-- 依赖：T1、T2、T6 互相独立；T3 依赖 T1、T2；T4 独立于 T3；T5 独立；T7 依赖 T5、T6；T8 依赖全部 -->

### T1：`engines.render.mix`（完成）

- **目标**：纯能力层的旁白混音。
- **涉及文件**：`backend/src/studio/engines/render/mix.py`、`backend/tests/engines/test_mix.py`、`backend/pyproject.toml`（import-linter：`engines` 契约不需新增，确认 `mix` 不 import `studio.timeline`）。
- **接口**：`AudioTrack(path: Path, start: float)`；`async mix_final(video: Path, tracks: Sequence[AudioTrack], duration: float, output: Path, *, music: AudioTrack | None = None) -> None`。`music` 本计划恒为 `None`，传入非空抛 `NotImplementedError`（子项目 3 再做侧链）。纯函数 `build_mix_command(...) -> list[str]` 返回 ffmpeg 参数，便于单测：每条轨 `adelay=<毫秒>|<毫秒>`，`amix=inputs=N:normalize=0:duration=longest`，再 `atrim=0:<duration>`/`apad` 保证时长，`-c:v copy -c:a aac -movflags +faststart -t <duration>`；无旁白轨时复制视频并加一条静音 AAC 轨，保证成片总有音轨。ffmpeg 失败抛 `MixError`，消息带 stderr 末尾若干行。
- **测试**：纯函数（命令构造：起点毫秒换算、轨数、无轨道分支、`music` 拒绝）；`slow`：用 ffmpeg 生成的正弦音和色块视频，两条轨起点不同，ffprobe 验证音轨为 aac、总时长等于 `duration`（±一帧）、音频长于/短于镜头时仍等于 `duration`、`faststart`（moov 在 mdat 前）；ffmpeg 失败（输入不存在）抛 `MixError` 且不留下半成品输出。
- **完成标准**：测试通过；输出写临时文件再原子改名。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_mix.py -v && uv run pytest tests/engines/test_mix.py -m slow -v`

### T2：`engines.render.html.video`（完成）

- **目标**：逐帧出图并编码为无声 MP4，带进度回调与可诊断的失败。
- **涉及文件**：`backend/src/studio/engines/render/html/video.py`、`backend/tests/engines/test_html_video.py`。
- **接口**：`async render_silent_video(page: PageLike, duration: float, output: Path, *, fps: int = 30, on_progress: Callable[[int, int], Awaitable[None] | None] | None = None) -> VideoStats`；`VideoStats(frames: int, seconds: float)`。纯函数 `frame_count(duration, fps)`、`frame_time(i, fps)`、`build_encode_command(...)`。帧用 `page.render_jpeg(t)`（与预览共用渲染器），经 `image2pipe` 交给 `ffmpeg -c:v libx264 -pix_fmt yuv420p -crf 15 -r <fps>`；输出先写 `*.tmp.mp4` 再改名。失败：场景抛错的异常原样向上（已含 `[scene <id> @lt=…]`），并在外层补 `t=<秒>`；ffmpeg 提前退出时读取 stderr 末尾，抛 `VideoEncodeError`；任何失败都终止 ffmpeg 子进程并删除临时文件。取消（`CancelledError`）同样清理。
- **测试**：纯函数表驱动（帧数向上取整、时刻、命令参数）；`slow`（真实 Chromium + ffmpeg，固定小场景，1 秒时长）：帧数 = 30、ffprobe 时长≈1s、无音轨、像素格式 yuv420p；进度回调按序单调、最后一次等于总数；场景在第 k 帧抛错 → 抛错信息含该时刻、临时文件被删、没有输出文件；单元层用 fake `PageLike` 与 fake ffmpeg 覆盖"ffmpeg 提前退出"。
- **完成标准**：测试通过；测速结论待 T8 汇总。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_html_video.py -v && uv run pytest tests/engines/test_html_video.py -m slow -v`

### T3：worker 分流与 HTML 成片（完成）

- **目标**：`final_render` 按项目引擎分流；HTML 路径产出 `final.mp4` 与 `final.json`。
- **涉及文件**：`backend/src/studio/worker.py`（拆分：Manim 路径保持原样，新增 `_run_html` 一类函数，必要时把 HTML 路径放进 `backend/src/studio/worker_html.py`，保持 `worker.py` 可读）、`backend/tests/test_worker.py`（沿用现有夹具，新增 HTML 用例）、`backend/tests/fixtures/`（复用 `animation_html/seed.py` 的 sky 夹具与 `html_engine/fakes.py`）。
- **要点**：
  1. 分流：`get_project(engine, job.project_id).settings.get("engine") == "html"` → HTML 路径；其余走原路径。
  2. 前置检查（任一失败 → `fail`，错误点名镜头，不启动浏览器、不拍快照）：读 `narrative/{narrative,timing}.json` → `narration_from_documents` → `build_timeline`（`TimelineError` 汇总原因）；每个镜头有非空 `animation/scenes/<id>.js`；`static_check` 与资产检查无错误（复用 `engines.render.html.static_check/assets`）；每个镜头的音频文件存在且在工作区内（`safe_path`）。
  3. 拍快照（与 Manim 一致，`reason="final_render"`）。
  4. 缓存键与命中：见全局约束；命中直接复用无声视频，跳过浏览器。
  5. 未命中：启动 `HtmlBrowser`，`assemble`（不带预览脚本）→ `open_page` → `render_silent_video`；`on_progress` 里 `update_progress` 并 `heartbeat`；结束关浏览器。写缓存（原子改名）。
  6. 混音：`mix_final`，`AudioTrack(path, start=timeline 中该镜头的 start)`；输出 `output/final.mp4`。
  7. 写 `output/final.json`：保留 `snapshot_id`、`scene_hashes`、`rendered_at`，新增 `engine: "html"`、`timeline_hash`、`audio_sources`（`{scene_id: audio_hash}`）。
  8. 任务失败时 `fail` 带错误；`final.mp4` 只在混音成功后才被替换（先写临时文件）。
- **测试**：用例用 fake 页面与 fake 混音（单元层，不启动 Chromium）：分流（html 与 manim 项目各走各的，manim 现有测试不改）；前置检查逐条失败的错误文本（缺镜头文件、空文件、静态检查错误、timing 不一致、音频缺失）且浏览器未被打开；`final.json` 字段；缓存命中跳过出帧、源码一变则重新出帧、`timeline_hash` 变则失效；渲染中途失败不留下 `final.mp4`、缓存无残留；进度与心跳被调用。`slow` 端到端见 T8。
- **完成标准**：Manim 路径现有 worker 测试全部通过；新增用例通过。
- **验证命令**：`cd backend && uv run pytest tests/test_worker.py tests/engines/test_worker.py -v`

### T4：api——动画阶段解析与 `scene_checks` 泛化（完成）

- **目标**：渲染任务、定稿、镜头检查状态对 `animation_html` 生效，老项目与 Manim 不变。
- **涉及文件**：`backend/src/studio/api/jobs.py`、`api/animation.py`、`api/scene_checks.py`、`backend/tests/api/`（新增 `test_html_render_flow.py`，补充现有 jobs/animation/scene_checks 用例）。
- **要点**：
  - 新增小函数（放 `api/animation.py` 或 `api/deps.py` 旁的合适位置，两个模块共用）：`animation_stage_of(project) -> str`：取项目 `settings["pipeline"]` 中的 `animation_html` 或 `animation`，没有 pipeline 字段（老项目）回落 `animation`。`create_render_job` 与 `finalize-render` 用它代替写死的 `"animation"`；锁定、忙碌、快照一致性判断不变。
  - `scene_checks`：按"阶段 → 工具名 + 镜头文件模板"表泛化：`animation` → `validate_scenes`/`render_preview`/`.py`；`animation_html` → `validate_scenes_html`/`render_preview_html`/`.js`。`compute_scene_checks` 通过项目的动画阶段名取表，会话也按该阶段列出。Manim 解析逻辑和文本形状完全不动。
  - `animation_html` 的 `validate_scenes_html` 文本归属规则（来自 2A 约定的输出形状）：调用参数带 `scene_id` → 结果只属于该镜头（`is_error` 决定通过与否）；不带 `scene_id` 且成功（首行 `全部 N 个镜头校验通过。`）→ 项目级通过；不带 `scene_id` 且失败 → 按行首 `镜头 <id>：` 点名失败镜头（`警告 镜头` 行不算失败）；失败但没有任何镜头被点名（页面级错误）→ 对所有镜头记为失败。`render_preview_html` 精确到 `args.scene_id`，图片取 `tool_result.images`。
- **测试**：阶段解析表驱动（html 项目、manim 项目、无 pipeline 的老项目）；html 项目 `POST /render` 要求 `animation_html` 未锁定，`finalize-render` 对 `animation_html` 定稿并标记完成、拒绝快照不一致；Manim 项目现有用例不改；`scene_checks` 对 html 的归属规则逐条（单镜头调用、全部通过、点名失败、页面级失败、警告行、预览图片、stale 判断用 `.js` 路径）。
- **完成标准**：`tests/api/` 全部通过；Manim 路径的 scene_checks 用例零改动。
- **验证命令**：`cd backend && uv run pytest tests/api -q`

### T5：api——预览端点（完成）

- **目标**：iframe 实时预览所需的三个只读端点。
- **涉及文件**：`backend/src/studio/api/html_preview.py`（新）、`backend/src/studio/main.py`（注册路由）、`backend/src/studio/api/schemas.py`（`HtmlPreviewMeta` 等）、`backend/tests/api/test_html_preview.py`。
- **接口**：
  - `GET /api/projects/{id}/animation/html-preview/meta` → `{ hash, duration, sections: [{ id, label, start, end, beats: [{start, end, cue_text}] }], audio: [{ section_id, url }] }`；`hash = page_hash(workdir, timeline)`；`url` 指向既有的叙事配音下载接口（先读 `api/endpoints.ts` 的 `narrative/audio/<id>.mp3` 用法，沿用同一端点，不新增）。
  - `GET .../html-preview/`（以及 `.../html-preview`）→ `assemble(workdir, timeline, preview=True).html`，`text/html`。
  - `GET .../html-preview/{path:path}` → 先查 `AssembledPage.scripts`（路径形如 `scripts/<name>`）与 `routes`（`fonts/…`、`style-fonts/…`、`assets/…`），内容类型沿用 `browser._content_type`；其余 404。`meta` 路由在 `{path}` 之前声明。
  - 所有响应带 `Cache-Control: no-store`、`Access-Control-Allow-Origin: *`。
  - 错误：项目不存在 404；时间轴不可用（`TimelineError`、缺文件）409，`detail` 为原因。
- **要点**：路径先 `unquote` 再按 `routes`/`scripts` 查表，不碰磁盘上的任意路径；`routes` 的目标文件做 `resolve()` 后必须在工作区或包字体目录内（符号链接指向外面的资源返回 404）；`/meta` 与页面共用同一次时间轴构建函数，抽到 `api` 内的小模块。
- **测试**：页面含预览脚本与 `window.__TIMELINE__`；`meta` 字段与哈希（改一个镜头文件、改 `lib`、改资产、改时间轴各自使 `hash` 变化，未改则不变）；脚本与字体、资产可取，类型正确；`..`、`%2e%2e`、`..%2f`、绝对路径、指向工作区外的符号链接资源 → 404；`meta` 不被当成资源路径；CORS 与 `no-store` 头；上游缺失/不一致 → 409 且 `detail` 点名原因；`audio` 只包含已配音的镜头。
- **完成标准**：端点测试全部通过；与 `assemble` 的路由表一致。
- **验证命令**：`cd backend && uv run pytest tests/api/test_html_preview.py -v`

### T6：前端基础——搬迁、语言、协议与时钟（完成）

- **目标**：画布所需的纯逻辑与跨 feature 的基础件先就位。
- **涉及文件**：`frontend/src/composables/useScenePlayback.ts`（+ spec，从 `features/canvas/narrative/` 搬来，叙事画布改 import）、`frontend/package.json` + `pnpm-lock.yaml`（`@codemirror/lang-javascript`）、`frontend/src/components/codeEditorLanguage.ts`（加 `'javascript'`）、`components/CodeEditor.vue`、`features/canvas/generic/fileKind.ts`（`.js` 用 `'javascript'`，更新其 spec）、`frontend/src/features/canvas/animation/htmlPreview/` 下的纯模块与 spec：`previewProtocol.ts`（构造 `seek`、解析来自 iframe 的 `ready`/`error`，按 `event.source` 过滤）、`previewClock.ts`（全局时间 ↔ 镜头内时间映射、音频 `currentTime` 加镜头起点、镜头刻度百分比、循环当前镜头的跳转、下一镜头）、`api/endpoints.ts`/`types/api.ts`/`composables/queries.ts`（`getHtmlPreviewMeta` 与 `useHtmlPreviewMetaQuery`，`queryKey` 含项目）。
- **要点**：搬迁保持 `useScenePlayback` 的行为与测试不变；不 import 别的 feature。`meta` 查询在收到 `workspace_changed`（现有事件 → 查询失效机制）后重新拉取；是否刷新 iframe 由 `hash` 变化决定，这个判断写成纯函数。
- **测试**：搬迁后的 `useScenePlayback.spec.ts`；时钟映射（镜头边界、尾部夹紧、未配音镜头的回退计时）、刻度计算（总时长为 0、单镜头）、协议（别的窗口的消息被忽略、畸形消息被忽略）、`hash` 变化判断；`fileKind` 的 `.js`；`CodeEditor` 的 javascript 语言能构造（沿用现有组件测试方式）。
- **完成标准**：`pnpm lint`、`vitest` 全绿；叙事画布行为不变。
- **验证命令**：`cd frontend && pnpm exec vitest run && pnpm run lint && pnpm exec vue-tsc --noEmit`（以 `make check` 里的实际命令为准）

### T7：前端——`HtmlAnimationCanvas` 与分发（完成）

- **目标**：三个标签的专属画布，`animation_html` 阶段用它。
- **涉及文件**：`frontend/src/features/canvas/animation/HtmlAnimationCanvas.vue`、`HtmlPreviewPane.vue`、`useHtmlPlayback.ts`（含 spec 与组件 spec）、`frontend/src/pages/ProjectWorkbenchPage.vue`（按阶段 key 分发，标签行 `actions` 插槽与 `AnimationCanvas` 一致）、必要时 `sceneStatus.ts`（镜头文件扩展名参数化，Manim 行为不变）。
- **要点**：
  - **镜头**标签：镜头列表来自 `meta.sections`（不依赖 `upstream/` 物化），附"文件是否存在"和 `scene-checks` 状态；复用 `SceneList`、`CodeEditor`（`javascript`）、保存栏与冲突状态机的做法；保存的 `stage` 为 `animation_html`；`meta` 返回 409 时显示原因而不是空白。
  - **实时预览**标签：iframe `sandbox="allow-scripts"`，`src` 为预览页地址加 `?v=<hash>` 以便刷新；传输控制（播放/暂停、带镜头刻度的进度条、循环当前镜头、`error` 横幅）；播放时钟与音频对齐按设计 §7.2；`hash` 变化才重载 iframe；`error` 只显示横幅，不影响编辑和成片；agent 运行中也可预览。
  - **成片**标签：直接复用 `FinalRenderPanel`（`scene-count` 取 `meta.sections.length`）；`v-show` 切换以保持轮询。
  - 视觉与现有画布一致（沿用设计系统组件，不引入新依赖）。
- **测试**：组件测试覆盖三个标签的渲染与切换、`meta` 409 的提示、保存请求的 `stage`、预览横幅、刻度点击跳转（用 fake iframe 窗口与 fake audio）；`ProjectWorkbenchPage` 的分发（`animation_html` → 新画布，`animation` → 旧画布）。
- **完成标准**：`make check` 前端部分全绿。
- **验证命令**：`cd frontend && pnpm exec vitest run && pnpm run lint`

### T8：端到端、实测、文档与验收（完成）

- **目标**：证据齐全，文档同步，计划进入待验收。
- **涉及文件**：`backend/tests/api/test_html_final_flow.py`（`slow`：fake 运行时流水线 → 种子镜头 → 预览端点 → 建渲染任务 → worker `run_once` → `final.mp4`/`final.json` → 定稿）、`backend/tests/engines/test_html_pool_recovery.py`（`slow`：杀掉池里的 Chromium 进程后下一次调用成功）、`backend/tests/smoke/test_smoke.py`（在 `animation_html` 冒烟用例末尾对产出的工作区调用 worker 渲染并断言 mp4 时长与时间轴一致，不新增模型调用）、`docs/references/html-video-render.md`（新）与 `README` 索引、`docs/ARCHITECTURE.md`（依赖表加入 `engines.render.mix`、`engines.render.html.video`、worker 依赖 `timeline`）、`docs/quality/QUALITY.md`、`docs/quality/tech-debt.md`（TD-69 ⑤ 的结论）、`docs/runbooks/verification.md`、`docs/plans/TODO.md`。
- **实测**：① 出帧速度（帧/秒）与不同时长成片的总耗时、成片体积，记录在 references；② 常驻浏览器的内存占用（连续若干次预览前后，以及空闲 10 分钟关闭后）；③ 预览与成片的音画偏差（L4 中以同一镜头的 beat 时刻对比）；④ 真实 SIGKILL 恢复。
- **L4**（控制者执行，隔离实例端口 8010/5174、独立 `STUDIO_DATA_DIR`）：创建 HTML 讲解项目，用种子脚本写入叙事与镜头，打开动画画布：三个标签、实时预览播放/拖动/循环、渲染成片、播放成片、定稿。
- **完成标准**：AC1–AC9 逐条勾选并写验证记录；`make check` 为绿；计划状态改为"待验收"。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow tests/api/test_html_final_flow.py tests/engines -v`

## 进度

- 2026-10-05：计划起草，2A 已验收并合并 main。
- 2026-10-05：T1–T8 全部完成，`make check` 全绿（后端 1948、前端 977），HTML 相关 slow 测试 33 个通过，真实模型冒烟通过（含成片渲染），L4 全链路通过；待整分支评审后交负责人验收。

## 下一步

整分支评审（独立评审者）→ 修复 Critical/Important → 交负责人验收；验收后合并 main、移到 `completed/`。

## 决策记录

- 预览与成片的时间轴来源都用工作区顶层 `narrative/{narrative,timing}.json`（设计 §7.1 写的是 `upstream/narrative/`）：顶层目录在动画阶段始终存在，与 worker 同源，不依赖 `upstream/` 要等第一轮才物化；叙事阶段被重新打开时预览会显示当前叙事，而不是定稿快照——接受，成片前会重新检查。
- `@codemirror/lang-javascript` 作为本计划批准的唯一新增前端依赖（设计 §7.2 要求"先确认 `CodeEditor` 支持 javascript"，实测不支持）。
- 无旁白轨道时混音输出静音 AAC 轨：保证成片总有音轨，播放器行为一致。
- 时间轴读取抽成 `studio.timeline.load.load_workspace_timeline`（计划没有）：worker 与预览端点要同一来源，放在纯能力层里只用 `pathlib`（含符号链接越界检查），不引入对 `workspace` 的依赖。
- `serve_page_path` 放在 `assemble.py`（计划没有）：浏览器层的 `page.route` 和预览端点共用一处查表，路径只在组装结果里查，不碰磁盘。
- worker 的 HTML 路径放进 `worker_html.py`，用可注入的 `HtmlBackend` 测试（计划写“必要时拆分”）；HTML 的 worker 测试在新文件 `tests/test_worker_html.py`，没有改现有 `tests/test_worker.py`。
- `ProjectWorkbenchPage` 的按阶段分发没有单测（页面过重，计划原写了测试）；由 L4 覆盖，QUALITY 已标注。
- 预览 iframe 改用自包含页面（见“意外与发现”）：新增 `GET .../html-preview/inline`、`assemble(inline=True)`、运行时读 `window.__ASSET_SRC__`，设计 §7.1 原来的“iframe 经 api 取页面和资源”改成“前端取一次自包含 HTML 设为 `srcdoc`”；资源端点保留用于调试。
- 前端 `HtmlAnimationCanvas` 的缓冲区初始化同时监听 `[fileContent, selectedSceneId]`（没有照抄 `AnimationCanvas` 只监听内容）：查询缓存命中时内容一上来就有值，只监听内容会让换镜头后一直“加载中”。

- 评审后去掉预览端点的 CORS：设计 §7.1 加它是为了让沙盒 iframe 取字体，改用 `srcdoc` 后没有别的源需要读，保留只会让任何网页都能读到镜头源码和旁白。
- 评审后缓存键改取自“交给浏览器渲染的那份组装结果”（`AssembledPage` 的页面、脚本、路由文件字节），`render_video` 直接接收这份结果：渲染期间镜头被改，缓存里存的仍是与键对得上的旧内容帧。
- 评审后每条旁白轨按镜头时长截断（`AudioTrack.max_seconds` → `atrim`）：配音比镜头长（timing 没更新）时不叠进下一镜头，与预览一致。

## 意外与发现

- **`apad` 无限流**：`amix` 后接裸 `apad` 加 `-t`，遇到引擎自己编码的视频时 ffmpeg 一直写（几分钟 64 MB），而 lavfi 生成的测试视频正常，所以第一版单元测试没发现；端到端慢测试挂住才暴露。改成 `apad=whole_dur=D,atrim=end=D` 并补回归测试（`references/html-video-render.md`）。
- **色域**：Canvas JPEG 是 `yuvj420p`，直接 `-pix_fmt yuv420p` 仍被标成 `yuvj420p`；改用 `scale=in_range=pc:out_range=tv,format=yuv420p`。
- **`test_subprocess_stdin` 守卫**：新增的 ffmpeg 子进程必须显式设置 `stdin`，首次提交被它拦下，补上后通过。
- **沙盒 iframe 取不到本机子资源（L4 发现）**：不透明源（`sandbox` 不带 `allow-same-origin`）的 iframe 对本机服务的请求，在内置浏览器里根本没有发出（api 日志里没有记录，连它自己的 `src` 页面和脚本都取不到），表现为页面不报错也永远不发 `ready`。同一页面在顶层、普通 iframe 都正常；`srcdoc` 内联脚本和字体的页面在沙盒里正常。改为自包含页面加 `srcdoc`。是否是该内置浏览器特有的策略没有在用户 Chrome 里验证，自包含方案不依赖这一点。
- **L4 中成片面板停在“排队中”**：内置浏览器窗格被收起时页面在后台，任务轮询没有推进，刷新后正常显示“已完成”并能播放；判断为后台标签页的轮询节流，没有单独验证。
- 真实模型写出的 3 个镜头（32.4 秒）在冒烟里渲染成片耗时 12.6 秒（含启动浏览器）。

## 阻塞

无。

## 整分支评审（独立评审者，opus，2026-10-05）

无 Critical。负责人随后决定：补测音画偏差（已做）、`docs/temp/` 加入 `.gitignore`（已做）、动画阶段隐藏直接定稿按钮（保留“重新打开”，`StageFinalizeButton` 新增 `reopenOnly`）、`POST /render` 在项目有运行中的一轮时返回 409（均先写红测试）。已修（均先写红测试）：I-1 worker 对未列入的异常（Playwright/ffmpeg/磁盘）兜底为 `failed`，`run_forever` 单次迭代出错不退出；I-2 `docs/temp/` 再次被我的 `git add -A` 带进历史，已重写分支历史移除（备份标签 `backup-html-engine-2b-pre-review`，验收后删）；M-1 内联脚本的 `</script` 转义不区分大小写；M-2 缓存键与渲染同源；M-3 快速点击时旧 `play()` 的 AbortError 不再把时钟错切到墙钟；M-4 镜头变少时停止播放；M-5 预览不再请求时间轴末尾那帧空白；M-6 旁白按镜头截断；M-9 去掉 CORS；M-10 AC7 如实改为未完全达成。延后：M-7（缓存键依赖人工 bump `ENGINE_VERSION`，内置字体未进键）、M-8（自包含预览页约 3 MB，每次哈希变化和切回标签都重取）登记为 TD-70。

## 验证记录

| 验收 | 命令 / 操作 | 结果 |
|---|---|---|
| AC1 | `uv run pytest tests/engines/test_mix.py` 与 `-m slow` | 快速 7 项、慢速 6 项通过（含 `apad` 回归） |
| AC2 | `tests/engines/test_html_video.py` 与 `-m slow` | 快速 16 项（纯函数、假 ffmpeg 失败/取消路径）、慢速 2 项（帧数 30、yuv420p、颜色往返、失败点名 `t=0.5` 且无残留）通过 |
| AC3 | `tests/test_worker_html.py`；`tests/api/test_html_final_flow.py`（slow） | 分流、六类前置失败、缓存命中与失效、渲染/混音失败保留旧成片、进度与心跳通过；端到端 1920×1080 H.264 加 AAC、时长 3.0 秒、`final.json` 带 `engine`/`timeline_hash`/`audio_sources` |
| AC4 | `tests/api/test_html_render_flow.py`、`test_scene_checks_html.py`，其余 `tests/api` | 389+ 项通过；Manim 路径用例零改动 |
| AC5 | `tests/api/test_html_preview.py` | 页面、资源、`meta`、`inline`、哈希、越界、符号链接、CORS、409 通过 |
| AC6 | `pnpm exec vitest run` | 977 项通过；`useScenePlayback` 搬迁后原测试不变 |
| AC7 | 隔离实例（api 8010、前端 5174、临时数据目录）：种子项目 → 三个标签 → 预览播放到 3.0 秒、收到 `ready`、无错误横幅 → worker 渲染 → 成片 3 秒可播放 → 定稿 | 通过；`animation_html` 与项目均完成。由于窗格被收起，后半段用 DOM 脚本而非截图验证，成片音画偏差用“beat 处白闪加 1 kHz 音”的夹具补测：4 个 beat 画面和音频相对期望均为 0 毫秒；预览偏差上限约两帧，为推算、未实测（`references/html-video-render.md`）|
| AC8 | `references/html-video-render.md`；`tests/engines/test_html_pool_recovery.py`（slow） | 出帧 30–135 帧/秒；SIGKILL 后重建、空闲回收通过；常驻 340–550 MB |
| AC9 | `make check`；真实模型冒烟 `make smoke SMOKE_ARGS="-k animation_html_claude_login"` | `make check` 全绿；冒烟 1 项通过（7 分 51 秒，9 次校验、5 次预览、无警告，成片 32.4 秒、渲染 12.6 秒） |
