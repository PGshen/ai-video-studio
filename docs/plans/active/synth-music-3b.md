# synth-music-3b：成片混音、配乐 api 与前端（多形态视频 子项目 3B）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 进行中 |
| 里程碑 | 多形态视频流水线 · 子项目 3/4 · 计划 3B |
| 设计依据 | [子项目 3 设计](../../design/2026-10-05-synth-music-reel.md)（已批准）§8、§9、§10；[ADR 0021](../../decisions/0021-HTML引擎与配乐阶段.md)；[3A 计划](../completed/synth-music-3a.md)（已合并）的决策记录；[ffmpeg 记录](../../references/ffmpeg.md) |
| 分支 | `synth-music-3b`（从 `main` 切出，3A 与其遗留修复合并之后） |
| 批准记录 | 设计已于 2026-10-05 批准（含 3B 的范围）；2026-10-05 负责人审阅通过本计划，开始实现 |

> 执行方式：Native（自己按任务顺序实现），整分支完成后由一个独立评审者评审一次；用 `claude-login` 做一次真实模型冒烟。本计划的「进度」「决策记录」就是账本。每个任务先写失败的测试，再实现。计划只写结构和意图，不写完整实现代码。

## 目标

3A 之后两种形态（动态图形短片、"讲解 + 合成背景乐"）已能在 agent 侧走完流水线，但还出不了成片，前端也听不到配乐。3B 补上这部分：

- worker 输出**带配乐的 MP4**：短片只有配乐；讲解有旁白，配乐被旁白压低（侧链）。
- 后端提供配乐的元数据、音频（支持 `Range`）和**不经 agent 的手动渲染**端点；实时预览的元数据带上配乐。
- 前端有 **`MusicCanvas`**（试听、看波形与事件、编辑脚本并手动渲染），**实时预览能放配乐**（短片以配乐为时钟，讲解里配乐跟随旁白）。

做到的标志：负责人在界面里创建短片项目，走完四个阶段，试听配乐，在预览里看到画面踩着音乐，出一个有声音的 MP4。

## 范围

**包含：**

- `engines.render.mix`：配乐轨（只有配乐；旁白 + 配乐的侧链压低），参数用真实 ffmpeg 实测后定。
- `worker_html`：去掉"带配乐或无旁白项目尚未实现"的守卫；前置检查（配乐文件在、与当前时间轴一致）；`final.json` 增加配乐哈希；短片无旁白的成片路径。
- 后端 api：`GET /music/meta`、`GET /music/audio`、`POST /music/render`；`html-preview/meta` 增加 `music`。
- 前端：`MusicCanvas` 与阶段分发；`useHtmlPlayback` 的配乐来源；类型、endpoints、查询。
- 测试：真实 ffmpeg 的混音数值测试（slow）、worker 与 api 的集成测试、前端 vitest、成片冒烟（真实模型）、L4。
- 文档同步，并把 3A 评审留下的与 3B 相关的事项一并处理（见「全局约束」末条）。

**不包含：**

- `concept`、`beatsheet` 的专用画布（继续用通用文件画布）；音乐导入与 MV（子项目 4）；歌词；变速曲；项目级分辨率与 fps。
- 侧链压低的**听感**校准（只验证数值，听感由负责人验收时判断，结论写进 references）。
- `POST /music/render` 的进度反馈（先同步返回；若实际耗时超过 60 秒再改成任务，记入 TODO）。

## 全局约束

- **混音（设计 §8.1）**：配乐统一重采样到 44.1 kHz 立体声，首尾各 15 ms 淡变防爆音；总时长用 `apad=whole_dur` + `atrim` + `-t` 钉死（沿用 2B 的踩坑结论：裸 `apad` 是无限流）；输出 AAC、`+faststart`、写临时文件再原子改名；失败不留半成品，已有的 `output/final.mp4` 保持不变。
- **只有配乐（短片）**：不加增益。**旁白 + 配乐**：配乐先乘 `gain_db`（讲解默认 −8 dB），首淡入 1 秒、尾淡出 1.5 秒，经 `sidechaincompress` 以旁白总线为侧链，再与旁白 `amix normalize=0`。侧链阈值、比例、起落时间由 T1 实测后定，并写进 `docs/references/ffmpeg.md`（带日期与命令）。
- **缓存**：画面缓存键不变（`timeline_hash` 已覆盖事件与能量）；音频不进缓存，每次重混。
- **前置检查**：`music/music.wav`、`music/events.json`、`music/analysis.json`、`music/render.json` 必须存在，且 `render.json` 的 `base_hash` 等于当前时间轴的 `base_hash`；否则报"配乐与当前时间轴不一致，需要在配乐阶段重新渲染"并点名具体原因。
- **时间轴来源**：worker、`html-preview`、`/music/render` 都读**项目工作区顶层**（`TimelineSources(prefix="")`），与成片一致；`upstream/` 只是 agent 某一轮开始时的副本，不作 api 的来源。这与设计 §9.1 "预览改用 `upstream/`"的说法不同（3A 决策记录已写明读取以顶层为准）；设计正文不改，差异记在本计划的决策记录里。
- **`/music/render`**：与 agent 的 `render_music` 共用 `render_music_core`（不复制逻辑）；有轮次在跑 → 409；沙箱不可用 → 409 加原因；校验失败不动旧产物（核心已保证）；路径只走 `workspace` 的安全解析，不按用户给的路径碰磁盘。
- **`/music/audio`**：`Range` 合法与非法（越界、格式错）都有明确状态码（206/416）；`Cache-Control: no-store`；只能返回 `music/music.wav`。
- **前端**：沿用现有分层——纯函数在 `*.ts` 并有 spec，composable 管状态，组件只做展示；不引入新依赖；不在组件里写时间换算。预览与成片的音画对齐允许有小偏差，以成片为准。
- **分层**：`api` 可依赖 `stages`（已有先例：`video_kinds`）与 `engines`；`engines.render.mix` 不依赖 `agent`/`stages`；不新增跨阶段 import。
- **测试标记**：需要真实 ffmpeg、Chromium、Seatbelt 的测试标 `slow`，不进 `make check`；真实模型冒烟标 `smoke`。
- **顺带处理**：manim 阶段 `stages/animation/render_preview.py` 的图片大小上限（≤ 400 kB JPEG，3A 冒烟发现，在 TODO 里）；若 3A 遗留修复分支尚未合并，先合并再开工。

## 评审重点

规格隐含、但最容易在实际使用中出问题的五类情况（每条在对应任务里加测试）：

1. **混音数值与失败路径**：旁白出现时背景乐确实被压低（`astats` 实测）、旁白停后回升；短片成片的总时长与视频一致、音轨非静音；配乐比视频短/长、配乐文件损坏或缺失、ffmpeg 失败时不留半成品、旧成片原样保留（T1、T2）。
2. **配乐过期**：节拍脚本改了而配乐没重渲染、配乐被手动改回旧版、`render.json` 缺失或哈希对不上——成片前置检查点名原因，不静默出旧配乐（T2）。
3. **手动渲染的并发与安全**：渲染进行中又点一次、有轮次在跑、沙箱不可用、脚本崩溃或超时——都返回明确状态与原因，旧产物不动；`audio` 端点对非法 `Range`、没有产物的项目返回合理状态（T3）。
4. **预览播放的时钟与回退**：浏览器拒绝自动播放时回退墙钟；循环、拖动、切镜头时配乐位置正确；短片没有旁白片段时以配乐为时钟；配乐文件在预览期间被重新渲染（URL 带版本）后不播旧音（T5、T6）。
5. **画布的空与异常状态**：没有产物（`rendered=false`）、波形为空、事件为空、渲染失败的报告展示；保存脚本时有轮次在跑；渲染按钮在渲染中的禁用与重入（T7）。

## 验收标准

- [ ] AC1：`mix_final` 支持配乐轨：只有配乐与旁白 + 配乐两种；真实 ffmpeg 下总时长钉在视频时长、音轨存在且非静音；旁白段背景乐被压低、旁白停后回升（`astats` 数值断言）；失败不留半成品（验证方式：`tests/engines/test_render_mix*.py`，`-m slow`）
- [ ] AC2：`run_html_job` 对短片与"讲解 + 合成背景乐"产出带音轨的成片；前置检查在配乐缺失或过期时点名原因；`final.json` 含配乐哈希；无配乐的讲解结果与改动前一致（验证方式：`tests/test_worker_html.py` 与 slow 的真实 Chromium + ffmpeg 用例）
- [ ] AC3：`GET /music/meta`、`GET /music/audio`（含 `Range`）、`POST /music/render`（含 409 两种）符合设计 §9.1，且旧产物在失败时不动（验证方式：`tests/api/test_music.py`）
- [ ] AC4：`html-preview/meta` 带 `music: { url, gain } | null`，URL 带版本；短片可用（验证方式：`tests/api/test_html_preview.py`）
- [ ] AC5：前端纯函数（配乐时钟映射、波形与事件标记坐标、播放来源选择）与 `useHtmlPlayback` 的配乐来源有单测，回退与循环有用例（验证方式：`pnpm exec vitest run`）
- [ ] AC6：`MusicCanvas` 三个标签（播放 / 脚本 / 事件）与空、失败状态有组件测试；阶段分发新增 `music`（验证方式：vitest）
- [ ] AC7：fake 运行时下，短片与"讲解 + 合成背景乐"从创建到成片的整条路径通过（集成测试），成片音轨由 ffprobe 验证（验证方式：`tests/api/test_synth_music_flow.py` 扩展，slow）
- [ ] AC8：真实模型（`claude-login`）短片冒烟走到成片，成片有音轨、时长与时间轴一致（验证方式：`make smoke SMOKE_ARGS="-k motion_reel_claude_login"`，证据写到 `data/evidence/synth-music/smoke/`）
- [ ] AC9：L4：在内置浏览器里创建短片项目，走完四个阶段（可用 3A 的种子产物加手动渲染），配乐画布能试听与看波形，实时预览有声音，能出成片并播放（验证方式：控制者截图与记录）
- [ ] AC10：ARCHITECTURE、QUALITY、runbook、references（ffmpeg 侧链参数与实测）、设计的"对总设计的补充"与 TODO 已同步；`make check` 全绿；整分支评审的 Critical/Important 已修

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->
<!-- 依赖：T1 独立；T2 依赖 T1；T3 独立；T4 依赖 T3；T5 依赖 T4；T6 依赖 T5；T7 依赖 T3、T5；T8 依赖 T2、T6、T7；T9 依赖 T8 -->

### T1：`engines.render.mix` 的配乐轨（完成）

- **目标**：`mix_final(music=…)` 可用；参数实测后定（设计 §8.1）。
- **涉及文件**：`backend/src/studio/engines/render/mix.py`、`backend/tests/engines/test_render_mix*.py`（现有测试的位置以仓库为准）、`docs/references/ffmpeg.md`。
- **接口与要点**：
  - `AudioTrack` 增加 `gain_db: float = 0.0`；新增 `MusicMix(track: AudioTrack, duck_under_narration: bool, fade_in: float, fade_out: float)`；`mix_final(..., music: MusicMix | None)`。
  - `build_mix_command`：无配乐的命令与改动前**逐字节一致**（回归）；短片（无旁白轨）：配乐 → `aresample` 44.1 kHz 立体声 → 增益 → 首尾 15 ms 淡变 → `apad=whole_dur`/`atrim`；旁白 + 配乐：旁白总线 `asplit`，配乐经 `sidechaincompress`，再 `amix normalize=0`，淡入淡出按参数。
  - 参数实测：用合成的旁白（带静音间隔的正弦段）与合成配乐（持续低频加高频），在真实 ffmpeg 里扫阈值、比例、起落时间，选出"旁白段平均压低 ≥ 6 dB、旁白停后 1 秒内回升到 ≥ 原电平 −2 dB、不泵"的一组；把扫描表和结论写进 `docs/references/ffmpeg.md`。
- **测试**：命令构造的表驱动（无配乐回归、短片、旁白 + 配乐、增益与淡变参数进入滤镜图）；`slow`：真实 ffmpeg 产出的时长（`ffprobe`，容差 0.05 秒）、音轨存在、`astats` 验证短片非静音、旁白 + 配乐在旁白段被压低而在间隔段回升、配乐短于或长于视频时仍钉死时长；失败（坏的配乐文件）不留 `.tmp` 且旧输出不动。
- **完成标准**：AC1；无配乐的现有测试不改一行也通过。
- **验证命令**：`cd backend && uv run pytest tests/engines -k mix -v && uv run pytest -m slow tests/engines -k mix -v`

### T2：`worker_html` 的配乐路径（完成）

- **目标**：成片渲染支持短片与"讲解 + 合成背景乐"（设计 §8.2）。
- **涉及文件**：`backend/src/studio/worker_html.py`、`backend/src/studio/worker.py`（若有形态判断）、`backend/src/studio/api/animation.py`（`finalize-render` 对短片的前置条件）、`backend/tests/test_worker_html.py`、`backend/tests/api/test_animation_finalize_render.py`（若存在）。
- **接口与要点**：
  - 去掉 `run_html_job` 对无旁白或带配乐项目的守卫；时间轴读取沿用 `TimelineSources(workdir, narration, music_source)`（3A 已支持）。
  - 前置检查新增 `_music_sources`：四个文件存在、`render.json` 的 `base_hash == loaded.base_hash`、`wav_hash` 与 `music.wav` 实际哈希一致；错误点名文件与原因（"配乐与当前时间轴不一致，需要在配乐阶段重新渲染"）。
  - 轨道：短片无旁白轨，只有 `MusicMix(duck=False, gain_db=0)`；讲解 + 背景乐：旁白轨不变，`MusicMix(duck=True, gain_db=-8, fade_in=1.0, fade_out=1.5)`；无配乐的讲解与改动前一致。
  - `final.json.audio_sources` 增加 `"music": <wav_hash>`；其余字段不变。
  - `api/animation.py` 的定稿渲染入口检查：短片没有旁白与配音也能进入渲染；若现有逻辑要求配音文件，改为按形态判断，并给出可读错误。
- **测试**：fake backend 的集成（短片、讲解 + 背景乐、无配乐讲解的回归）；前置检查每种失败一条用例；`final.json` 字段；slow：真实 Chromium + ffmpeg 渲染短片小项目，`ffprobe` 验证音轨与时长，`astats` 验证非静音。
- **完成标准**：AC2。
- **验证命令**：`cd backend && uv run pytest tests/test_worker_html.py tests/api -k "render or worker_html" -v && uv run pytest -m slow tests/test_worker_html.py -v`

### T3：音乐 api——`meta`、`audio`、`render`（完成）

- **目标**：设计 §9.1 的三个端点，行为稳健。
- **涉及文件**：新建 `backend/src/studio/api/music.py`；`backend/src/studio/api/schemas.py`；`backend/src/studio/main.py`（挂路由）；`backend/tests/api/test_music.py`；读一遍 `api/files.py` 的忙碌检查与安全解析写法后照用。
- **接口与要点**：
  - `GET /api/projects/{id}/music/meta` → `{ hash, duration, bpm, events, waveform, metrics, rendered }`；没有产物时 `rendered=false`、其余为空；`hash` 取自 `render.json` 的 `wav_hash`；`metrics` 来自 `analysis.json`。项目没有配乐阶段（`music_source != "synth"`）→ 404。
  - `GET /api/projects/{id}/music/audio`：返回 `music/music.wav`，支持 `Range`（206；非法或越界 416），`Cache-Control: no-store`，`Accept-Ranges: bytes`；没有产物 404。
  - `POST /api/projects/{id}/music/render`：读时间轴（顶层，`with_music=False`）与 `section_energy`，调用 `render_music_core`，沙箱包装用 `studio.stages.music.tool.sandbox_wrapper`；返回与工具同形的报告（文本摘要、指标、`warnings`、`errors`、分析图 base64——压成 ≤ 400 kB JPEG，复用 `compress_picture`）；失败返回 200 加 `ok=false` 与错误列表（脚本问题是业务结果，不是 HTTP 错误）；有轮次在跑 → 409；沙箱不可用 → 409 加原因；同一项目已有手动渲染在跑 → 409（进程内每项目一把锁）。
  - 决策项（在计划决策记录里写下结论）：手动渲染成功后是否拍快照——先读 `api/files.py` 保存文件的做法，保持一致；`finalize_blockers` 以顶层为准，所以手动渲染后配乐阶段可直接定稿。
- **测试**：用 3A 的参考合成脚本与种子项目；三个端点的成功与每种失败；`Range` 的合法/非法/多段（不支持多段则明确返回 416 或整段，写进测试）；并发两次渲染第二次 409；渲染失败旧产物逐字节不变；`audio` 不能被路径参数带到别的文件。
- **完成标准**：AC3。
- **验证命令**：`cd backend && uv run pytest tests/api/test_music.py -v && uv run lint-imports`

### T4：`html-preview/meta` 带配乐（完成）

- **目标**：预览知道有没有配乐、在哪取、放多大声（设计 §9.1）。
- **涉及文件**：`backend/src/studio/api/html_preview.py`、`backend/src/studio/api/schemas.py`（`HtmlPreviewMusic`）、`backend/tests/api/test_html_preview.py`、`frontend/src/types/api.ts`。
- **接口与要点**：`HtmlPreviewMeta.music: { url, gain } | None`；`url` 指向 `/music/audio?v=<wav_hash>`；`gain` 是线性增益（短片 1.0，讲解背景乐 10^(−8/20)）；配乐没渲染或与时间轴不一致时为 `None`（预览照常出画面，由画布提示"配乐未渲染"）；短片的 `audio` 为空、`beats` 为空（3A 已支持）。
- **测试**：短片、讲解 + 背景乐、无配乐三种；URL 的版本随 `wav_hash` 变化；配乐过期时为 `None`。
- **完成标准**：AC4。
- **验证命令**：`cd backend && uv run pytest tests/api/test_html_preview.py -v`

### T5：前端基础——类型、endpoints、查询与纯函数（完成）

- **目标**：把 api 接进前端，并把所有换算写成有测试的纯函数。
- **涉及文件**：`frontend/src/types/api.ts`（`MusicMeta`、`MusicRenderReport`、`HtmlPreviewMeta.music`）、`frontend/src/api/endpoints.ts`（及 `endpoints.spec.ts`）、`frontend/src/features/canvas/music/musicQueries.ts`（查询与渲染 mutation，沿用现有 query 写法）、`frontend/src/features/canvas/music/waveform.ts`（波形点 → 画布坐标、事件与段落标记坐标、点击 x → 时间）、`frontend/src/features/canvas/animation/htmlPreview/previewClock.ts`（配乐时钟换算）及各自 spec。
- **接口与要点**：`timeToX(t, duration, width)`、`xToTime`、`waveformPath(points, width, height)`、`eventMarkers(events, duration, width)`；预览的配乐映射：短片 `t = music.currentTime`（循环取模）；讲解 `music.currentTime = t`（目标位置与偏差超过 0.3 秒才重设，避免抖动）。全部纯函数、不碰 DOM。
- **测试**：每个函数的边界（时长为 0、宽度为 0、空数组、越界时间、负时间）；endpoints 的路径与编码。
- **完成标准**：AC5 的纯函数部分。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/canvas src/api`

### T6：`useHtmlPlayback` 的配乐来源（完成）

- **目标**：实时预览能放配乐（设计 §9.2）。
- **涉及文件**：`frontend/src/features/canvas/animation/htmlPreview/useHtmlPlayback.ts`（及 spec）、`HtmlPreviewPane.vue`、`HtmlAnimationCanvas.vue`（传入 `meta.music`、显示"配乐未渲染"提示与静音开关）。
- **接口与要点**：
  - 短片（`meta.audio` 为空、有 `music`）：配乐的 `currentTime` 是时钟；循环整片或当前段；点镜头按钮 = 跳到该段起点；浏览器拒绝自动播放 → 回退墙钟（行为与现有旁白回退一致）。
  - 讲解 + 背景乐：旁白仍是时钟，配乐用另一个 `Audio`，音量 = `gain`，镜头切换与循环时按 `t` 对齐；偏差小于阈值不重设。
  - `meta.music` 的 URL 变了（重新渲染）时丢弃旧 `Audio`；组件卸载时全部暂停并移除监听；静音开关只静音配乐。
  - `createAudio` 注入沿用，便于测试。
- **测试**：假 `Audio` 与假帧：短片以配乐为时钟、循环、拖动、被拒绝自动播放时回退；讲解里配乐跟随与偏差阈值；URL 变化换源；静音；卸载清理。
- **完成标准**：AC5。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/canvas/animation`

### T7：`MusicCanvas` 与阶段分发（完成）

- **目标**：配乐阶段有自己的画布（设计 §9.2）。
- **涉及文件**：`frontend/src/features/canvas/music/{MusicCanvas,MusicPlayer,WaveformView,EventTable,RenderReport}.vue` 及 spec；`frontend/src/pages/ProjectWorkbenchPage.vue`（`stage === 'music'` 分支，定稿按钮与侧栏切换沿用其他阶段的写法）。
- **接口与要点**：
  - 播放标签：`<audio>` 播放器、波形（canvas 绘制，点击跳转）、段落与事件标记、`analysis.png`（若有，用现有文件内容接口取图）、指标摘要、"音色、和声、混响量与声像无法由指标判断，请试听"的固定提示；`rendered=false` 时显示空状态与"去渲染"。
  - 脚本标签：复用现有 `CodeEditor`（python），保存走现有文件保存；旁边"渲染"按钮调 `POST /music/render`，渲染中禁用并显示"渲染中"，完成后刷新 `meta` 与图；失败显示错误列表；有轮次在跑时按钮禁用并说明原因。
  - 事件标签：事件表（名称、类型、起止），点击跳转播放位置。
  - `concept`、`beatsheet` 仍走 `FileCanvas`。
- **测试**：组件测试覆盖——有产物、没产物、渲染中、渲染失败、有轮次在跑、点击波形与事件跳转；阶段分发的页面测试。
- **完成标准**：AC6。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/canvas/music src/pages && pnpm run lint && pnpm exec vue-tsc --noEmit`（以 `package.json` 里的类型检查命令为准）

### T8：整流水线集成、真实模型冒烟与成片（待开始）

- **目标**：证明短片与"讲解 + 合成背景乐"能一路出成片（AC7、AC8）。
- **涉及文件**：`backend/tests/api/test_synth_music_flow.py`（扩展）、`backend/tests/smoke/test_smoke.py::test_motion_reel_claude_login`（扩展到成片）、`backend/tests/smoke/support.py`。
- **接口与要点**：
  - 集成（fake 运行时）：创建 → 各阶段产物（3A 的假 agent 行为）→ 定稿 → `finalize-render` → `final.mp4` 与 `final.json`；短片与讲解各一条；slow 的版本用真实 ffmpeg 与 Chromium，`ffprobe` 验证音轨与时长。
  - 冒烟：在 3A 冒烟的画面阶段之后触发成片渲染（真实 Chromium + ffmpeg，不再调模型），断言 `final.mp4` 存在、有音轨、时长与时间轴相差 ≤ 0.1 秒、`final.json` 含配乐哈希；证据 JSON 增加成片信息。冒烟前先在隔离实例里用 3A 冒烟留下的产物手动出一次成片，确认流程通了再花钱。
  - 讲解 + 背景乐不单独跑真实模型冒烟（成本），由 slow 的集成测试覆盖。
- **完成标准**：AC7、AC8（附耗时、费用、各阶段轮数、警告）。
- **验证命令**：`cd backend && uv run pytest -m slow tests/api/test_synth_music_flow.py -v`；`make smoke SMOKE_ARGS="-k motion_reel_claude_login"`

### T9：L4、文档同步与收尾（待开始）

- **目标**：完成 L4（AC9）与文档同步（AC10）。
- **涉及文件**：`docs/ARCHITECTURE.md`、`docs/quality/QUALITY.md`、`docs/runbooks/verification.md`（L4 步骤与冒烟命令）、`docs/references/ffmpeg.md`、`docs/design/2026-10-05-synth-music-reel.md` 的"对总设计的补充"处只追加、不改正文（若需改正文走升级流程）、`docs/plans/TODO.md`、本计划的验证记录。
- **接口与要点**：
  - L4（控制者，隔离实例：api 8010、前端 5174、临时数据目录、假运行时；用 3A 的种子函数建项目）：创建短片项目；配乐阶段打开 `MusicCanvas`，试听、点波形与事件跳转、改脚本后点渲染；动画阶段的实时预览有声音、拖动与循环正确；出成片并在成片标签播放；"讲解 + 合成背景乐"同样走一遍，听到旁白时背景乐被压低（用 `astats` 的数值或耳听）；多张截图拼成一张联系表一起检查，细节处再单独放大。
  - 文档：ARCHITECTURE（`engines.render.mix` 的配乐、`api.music`）、QUALITY（新模块行）、runbook（L4 与冒烟）、references（ffmpeg 侧链实测）、TODO（子项目 3 整体完成；`concept`/`beatsheet` 专用画布、手动渲染进度反馈、侧链听感校准保留为待办）。
- **测试**：`make check` 全绿；全部 `slow` 测试。
- **完成标准**：AC9、AC10；整分支评审后修掉 Critical/Important，Minor 记入账本与 TODO。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow -v`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-05 — 计划写成，负责人审阅通过，开工
- 2026-10-05 — T7 `MusicCanvas` — 播放/脚本/事件三标签（`v-show`，切换不打断播放）；`MusicPlayer`（播放器、`WaveformView` SVG 波形与段落/事件/播放位置、指标、分析图、固定的"需要试听"提示）、`EventTable`、`RenderReport`、`musicView.ts`；脚本标签编辑 `music/compose.py`（保存走阶段 `music`），手动渲染在忙碌、未保存、无脚本时禁用并说明原因；`ProjectWorkbenchPage` 新增 `music` 分支（定稿按钮沿用）；组件与纯函数测试 40 条
- 2026-10-05 — T6 预览播放的配乐来源 — `useHtmlPlayback`：短片以配乐 `currentTime` 为时钟（贴合容差 0.05 秒、拒绝自动播放回退墙钟）；讲解里旁白是时钟、配乐 −8 dB 跟随（漂移 > 0.3 秒才重设，拒绝不影响旁白）；URL 变了换源并保持位置、配乐没了就停；`setMuted`；`HtmlPreviewPane` 加静音按钮与"配乐未渲染或已过期"提示，`HtmlAnimationCanvas` 按项目 `music_source` 计算 `scoreMissing`；新增 composable 测试 18 条、组件测试 3 条
- 2026-10-05 — T5 前端基础 — 类型（`MusicMetaOut`、`MusicRenderOut`）、endpoints（`getMusicMeta`、`musicAudioUrl`、`renderMusic`）、`queryKeys.musicMeta` 与 `useMusicMetaQuery`/`useRenderMusicMutation`（工作区失效时一并刷新配乐 meta）；纯函数 `waveform.ts`（`timeToX`/`xToTime`/`waveformPeaks`/`eventMarkers`/`sectionBands`）与 `previewClock.ts`（`playbackMode`/`musicClockTime`/`needsRealign`）及单测
- 2026-10-05 — T4 `html-preview/meta.music` — `{url, gain}`，URL 带 `wav_hash`；只在产物存在、`base_hash` 与 `wav_hash` 都对得上时给，否则 `null`；短片 gain 1.0、讲解 −8 dB 线性值；讲解背景乐的默认混音常量（−8 dB、淡入 1 秒/淡出 1.5 秒）移到 `engines.render.mix` 让成片与预览共用；前端 `HtmlPreviewMeta.music` 类型；`test_html_preview.py` 新增 4 条
- 2026-10-05 — T3 音乐 api — `api/music.py`：`meta`（含 `stale`、`sections`，损坏产物当作未渲染）、`audio`（`FileResponse` 的 Range：206、尾部范围、非法 400/416、软链接逃逸 404）、`render`（共用 `render_music_core`；脚本问题 200 + `ok=false`；轮次在跑 / 已有手动渲染 / 无沙箱 / 时间轴不可用 409）；`tests/api/test_music.py` 20 条；`section_energy` 抽到 `stages/music/sources.py`，`metrics_of` 公开
- 2026-10-05 — T2 `worker_html` 配乐路径 — 去掉守卫；前置检查（四个文件、`base_hash`、`wav_hash`）；短片只有配乐，背景乐 −8 dB + 侧链 + 淡入 1 秒/淡出 1.5 秒；`final.json.audio_sources.music`；新测试 `tests/test_worker_html_music.py`（成功 2、前置检查 7、旧成片保留 2、无配乐回归 1）+ slow 真实 Chromium + ffmpeg 2（短片音轨非静音、时长一致；讲解加配乐）；`FakeBackend` 移到 `fixtures/html_engine/worker_fakes.py`；`finalize-render` 与 `POST /render` 与形态无关，无需改
- 2026-10-05 — T1 `engines.render.mix` 配乐轨 — `MusicMix`、`AudioTrack.gain_db`、命令构造 7 条（无配乐不变、只有配乐、增益与淡变、侧链、不压低、无旁白不压）+ slow 4 条（时长与非静音与无爆音、配乐长短都钉时长、侧链压低 ≥ 6 dB 且 1 秒后回升、坏文件不留输出）；侧链定值 `0.03:6:10:400`，扫描表写进 `references/ffmpeg.md`

## 下一步

- 负责人审阅本计划；通过后，3A 遗留修复分支的真实模型冒烟通过并合并进 `main`，再从 `main` 切 `synth-music-3b`，从 T1 开始（T1、T3 互相独立，可先做任意一个）。

## 决策记录

<!-- 日期 — 决定 — 原因 — 影响。 -->

- 2026-10-05 — T2：时间轴本身因配乐声明的 duration 与节拍脚本不符而失败时（改了小节数），`run_html_job` 在错误后追加"到配乐阶段重新渲染"的提示；只改标签等不改时长时由 `base_hash` 前置检查报"配乐与当前时间轴不一致" — 两种都点名原因 — 无风险。
- 2026-10-05 — 时间轴来源：api 与 worker 都读工作区顶层，不用 `upstream/`（修正设计 §9.1 的措辞）— `upstream/` 只是 agent 某轮开始时的上游副本，在 api 里可能不存在或已过期；顶层与成片一致 — 无代码风险，设计正文不改，仅在此记录。
- 2026-10-05 — T3：手动渲染成功后不拍快照 — 与 `PUT /files` 保存文件一致（它也不拍）；`finalize_blockers` 以 `upstream/` 为准的局限在 agent 轮次里仍在，但手动渲染后用户再开一轮时 `upstream/` 会重建，影响不大。手动渲染期间用户又开了一轮 agent：两边各自原子发布，交错的话 `render.json` 的 `wav_hash` 对不上，成片前置检查点名 — 单人本地使用，不为此给 `TurnRunner` 加锁。
- 2026-10-05 — T3：时间轴来源用项目 `settings.narration` 决定（`TimelineSources`），不用 `infer_sources` 的"看有没有 beatsheet 文件"推断 — 推断在 beatsheet 被删时会误判成讲解 — 无。
- 2026-10-05 — T7：波形用 SVG 而不是 canvas（计划写的是 canvas）— jsdom 里没有 canvas 绘图上下文，SVG 能直接断言条形、标记与点击；1000 个点的 `<rect>` 开销可忽略 — 无。
- 2026-10-05 — 手动渲染同步返回 — 3A 冒烟里一次合成约 1 秒，加重定时与分析也远小于 60 秒 — 若实际更慢，改成任务并记入 TODO。
- 2026-10-05 — 讲解 + 背景乐不单独做真实模型冒烟 — 成本高、画面阶段的流程已由 3A 的短片冒烟验证，音轨由 slow 的真实 ffmpeg 测试验证 — 若负责人要求，补一个。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 暂无

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 待填
