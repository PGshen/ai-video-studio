# import-music-4b：上传、画布、预览与成片——导入音乐与音乐 MV

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成（2026-10-06 验收，合并到 main；成片画面效果一般，改进另立事项见 TODO） |
| 里程碑 | 多形态视频流水线·子项目 4（4B） |
| 设计依据 | [4B 设计增量](../../design/2026-10-05-import-music-mv-4b.md)（已批准 2026-10-05）；[导入音乐与音乐 MV 设计](../../design/2026-10-05-import-music-mv.md) §7、§8；[4A 计划](../completed/import-music-4a.md) |
| 分支 | `import-music-4b` |
| 批准记录 | 计划 2026-10-05 批准（负责人选 native 执行）；2026-10-06 负责人看了冒烟成片，认为效果一般，需靠对话与风格库控制画面；功能验收通过 |

## 目标

用户在「音乐 MV」项目里上传一首歌，在音乐画布上看到能量曲线、网格与段落，在画面预览里听到按截取区间对齐的原曲，渲染出音轨取自原曲的 MP4；创建音乐 MV 项目的入口正式开放；用 `docs/temp/海阔天空.mp3` 走通一次真实的端到端冒烟。

## 范围

**包含：**

- 后端：音频探测（`ffprobe`）；上传端点；`music/meta`、`music/audio` 的导入形态；预览的 `music.offset`；`mix.py` 的 `source_start`；`worker_html` 的导入分支、缓存键与 `final.json`；放开 `import` 入口。
- 前端：表单上传请求（带进度）、类型与查询；上传区；导入形态的音乐画布（能量曲线 + 网格/段落/区间叠加 + 分析摘要 + 校验结果）；实时预览按 `offset` 起播与同步。
- 冒烟脚本与文档：端到端冒烟（真实歌曲、本地 Claude 登录）、`docs/references/` 的实测记录、QUALITY/glossary/ARCHITECTURE 更新。

**不包含：**

- 画布内手改 `sections.json`；歌词；变速曲；多首歌；在线音乐服务；4A 已记录的已知缺口（设计 §11）。
- 把冒烟纳入 `make check`（冒烟默认不跑）；把歌曲放进仓库或测试夹具。

## 验收标准

- [x] AC1：`POST /api/projects/{id}/music/source` 的校验——非 `import` 项目、运行中的一轮、非白名单扩展名、超过 150 MB（含恰好等于上限）、内容不是音频、时长不在 5–600 秒——都返回约定的状态码与中文原因；成功时写入 `music/source.<ext>`、旧 `source.*` 被清掉、失败不留临时文件也不动旧文件。（验证：`tests/api/test_music_upload.py`）
- [x] AC2：`music/meta` 的导入形态返回源文件、分析摘要、网格、段落、区间、能量、`sections_check`、`stale`；换歌后 `stale=true`；合成形态的响应与既有测试不变；`music/audio` 在导入形态返回源文件并支持 `Range`。（验证：`tests/api/test_music_import_meta.py`、`tests/api/test_music.py`）
- [x] AC3：`html-preview/meta` 的 `music` 在导入形态带 `offset`（= 有效截取区间起点）、增益 1.0、地址带源哈希；源文件被换或未分析时为 `null`。（验证：`tests/api/test_html_preview.py`）
- [x] AC4：`mix.py` 能从源文件的 `source_start` 秒起截取；用已知音调的音频验证截取起点；淡出起点与补静音按成片时长算；合成形态的既有用例不变。（验证：`tests/engines/test_mix.py`）
- [x] AC5：`worker_html` 导入分支：成片时长等于时间轴时长；源文件在检查后被换（哈希不符）报错；缺 `analysis.json`/`sections.json` 报明确原因；缓存键随源哈希与区间变化；`final.json` 记录 `audio_sources.music`；合成形态与讲解的既有用例不变。（验证：`tests/test_worker_html_music.py`、`tests/api/test_html_final_flow.py`）
- [x] AC6：前端上传区、导入形态画布、预览 `offset` 同步的单元测试全部通过，`pnpm lint` 与 `pnpm exec vue-tsc`（项目已有的类型检查命令）无错误。（验证：vitest、`make check`）
- [x] AC7：`GET /api/video-kinds` 里音乐 MV 预设可选，创建项目对话框能选中并创建 `music_source=import` 的项目。（验证：`tests/api/test_video_kinds.py`、前端 `VideoKindPicker.spec.ts`）
- [x] AC8：L4 浏览器验证：上传区、能量曲线与叠加、点击跳转、预览播放与拖动同步（控制者在内置浏览器截图）。
- [x] AC9（读数、成片、耗时已记录；强拍相位、段落与淡入淡出待负责人试听）：真实冒烟：`docs/temp/海阔天空.mp3` 走完 `concept → music → beatsheet → animation_html` 并渲染出带原曲音轨的成片；记录出帧耗时、成片大小与拟合读数；强拍相位与段落由负责人试听核对。（验证：`make smoke` 的新用例、`docs/references/import-music-mv.md`）

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：音频探测与上传端点（完成）

- **目标**：用户能把一首歌安全地放进项目的 `music/source.<ext>`。
- **涉及文件**：新建 `backend/src/studio/engines/audio/probe.py`、`backend/src/studio/api/music_import.py`；修改 `backend/src/studio/api/schemas.py`、`backend/src/studio/api/music.py`（`_require_score_project` 按 `music_source` 分流）、`backend/src/studio/main.py`（注册新 router）；测试 `backend/tests/engines/test_audio_probe.py`、`backend/tests/api/test_music_upload.py`
- **接口与要点**：
  - `probe.py`（纯能力层，只依赖标准库）：`class AudioProbeError(ValueError)`；`@dataclass(frozen=True) class AudioProbe: duration: float; codec: str`；`async def probe_audio(path: Path, *, timeout: float = 15.0) -> AudioProbe`——用 `ffprobe -v error -select_streams a:0 -show_entries stream=codec_name:format=duration -of json`；没有音频流、`duration` 缺失/非有限、ffprobe 不存在、超时、非零退出都抛带中文原因的 `AudioProbeError`。`engines` 的 import-linter 契约不变。
  - `music_import.py`：`MAX_UPLOAD_BYTES = 150 * 1024 * 1024`；`router`（prefix `/api`）的 `POST /projects/{project_id}/music/source`（multipart，字段 `file`；`python-multipart` 已在锁文件里，若运行环境没有就停下来问，不要自己加依赖）。校验顺序固定：项目存在（404）→ `music_source == "import"`（404 "这个项目没有导入音乐"）→ 没有运行中的一轮（409，用 `turn_runner.is_project_busy`）→ 扩展名在 `stages.common.music_source.SOURCE_EXTENSIONS`（422，扩展名取原文件名的最后一段并小写，原文件名只用来取扩展名，**不参与任何路径拼接**）→ 边读边计数写入工作区临时文件，超过 `MAX_UPLOAD_BYTES` 立即中止（422）→ `probe_audio` 通过且 `5 ≤ duration ≤ 600`（取 `engines.audio.song` 的常量，422 并带原因）。通过后在**同一个调用里**清掉旧的 `music/source.*`，再把临时文件原子改名为 `music/source.<ext>`；任何一步失败都清理临时文件、不动旧文件。路径只走 `workspace.safe_path`/`project_dir`。
  - `async def` 端点：忙碌检查与"登记上传中"之间不 `await`（同 `api.music` 的约定）；同一项目已有上传在进行时 409（`request.app.state` 上加一个集合，与 `music_renders` 同样的初始化方式）。
  - 响应 `MusicSourceOut{filename: str, size: int, sha256: str, duration: float}`；不触发分析。
  - 先读 `api/music.py` 的头部注释与 `_require_score_project`，改成 `_require_music_project(engine, project_id) -> tuple[Literal["synth","import"], bool]`（返回形态与是否有旁白），保留合成形态的 404 文案，既有测试不改。
- **测试**（先写）：AC1 逐条（用 `audio_fixtures` 生成短 wav/mp3；内容是文本但扩展名 `.mp3`；`../x.mp3` 与含中文空格的文件名；恰好等于上限与多 1 字节——上限用 monkeypatch 改小以免真写 150 MB；零字节文件）；换歌清旧文件（先传 `.mp3` 再传 `.wav`，只剩 `.wav`）；失败时旧 `source.*` 原样、`music/` 与临时目录里没有残留；上传中途客户端断开（用 `TestClient` 流式请求或直接调用端点函数模拟读取异常）不留临时文件；`probe_audio` 各错误。
- **完成标准**：AC1 满足。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_audio_probe.py tests/api/test_music_upload.py tests/api/test_music.py -q`；`make check`

### T2：`music/meta` 与 `music/audio` 的导入形态（完成）

- **目标**：画布和预览能拿到导入形态需要的全部信息，并能播放源文件。
- **涉及文件**：`backend/src/studio/api/music_import.py`（加 `build_import_meta`）、`backend/src/studio/api/music.py`、`backend/src/studio/api/schemas.py`；测试 `backend/tests/api/test_music_import_meta.py`、`backend/tests/api/test_music.py`
- **接口与要点**：
  - `schemas.py`：`MusicMetaOut` 增加 `form: Literal["synth","import"] = "synth"` 与导入形态字段（合成形态保持默认值，序列化结果新增字段不影响现有断言，必要时更新 `tests/api/test_music.py` 里对整个字典的断言）：`source: MusicSourceInfo | None`（`filename, size, sha256, duration`；`duration` 只有在 `analysis.source_hash == sha256` 时取分析里的时长，否则为 `None`——不为取时长对每次 meta 请求再跑一次 `ffprobe`，见决策记录）、`analysis: MusicAnalysisOut | None`（`bpm, confidence, residual_ms, duration, warnings`）、`grid: MusicGridOut | None`（`bpm, offset, downbeats`；**有效值**：`sections.json` 的覆盖优先，用 `timeline.imported.effective_grid`）、`range: MusicRangeOut | None`（`start, end`；有效区间，同 `timeline.imported` 的规则）、`energy: MusicEnergyOut | None`（`hop, values`，整曲，不按区间截）、`sections_check: SectionsCheckOut | None`（`ok, errors, warnings`，来自 `stages.music.validate_sections.check_workspace`）。导入形态下 `rendered` 的含义是"已上传源文件"，`hash` 是源文件 `sha256`，`stale` 是 `analysis.source_hash` 与当前源文件哈希不一致，`sections` 取 `sections.json`（缺失时为空列表），`duration` 取分析时长（未分析为 `None`）。
  - `build_import_meta(workdir) -> MusicMetaOut`：只读文件，所有文件缺失/损坏都降级成对应字段为 `None`，不抛；哈希用 `workspace.file_sha256`（已有 mtime/size 缓存）。
  - `music/audio` 导入形态：`stages.common.music_source.find_source(workdir / "music")` 解析源文件，媒体类型按扩展名（mp3 `audio/mpeg`、wav `audio/wav`、m4a `audio/mp4`、flac `audio/flac`、ogg `audio/ogg`），`FileResponse` 处理 `Range`，`no-store`；路径走 `safe_path`；没有源文件 404 "还没有上传音乐"。
  - `render` 端点在导入形态返回 404 "导入形态没有合成渲染"。
- **测试**（先写）：AC2 各状态（未上传；已上传未分析；已分析无 `sections.json`；已分析且校验通过；`sections.json` 有错；换歌后 stale；`analysis.json`/`sections.json` 损坏）；有效网格取 `sections.json` 覆盖值；`audio` 的 `Range` 请求（`bytes=0-99` 返回 206 与正确内容）与媒体类型；合成形态响应的既有字段与行为不变。
- **完成标准**：AC2 满足。
- **验证命令**：`cd backend && uv run pytest tests/api/test_music_import_meta.py tests/api/test_music.py -q`；`make check`

### T3：预览的 `music.offset`（完成）

- **目标**：画面预览知道导入音乐要从哪一秒开始放。
- **涉及文件**：`backend/src/studio/api/html_preview.py`、`backend/src/studio/api/schemas.py`；测试 `backend/tests/api/test_html_preview.py`
- **接口与要点**：
  - `HtmlPreviewMusic` 增加 `offset: float = 0.0`（秒，文档字符串写清"音频时间 = 预览时间 + offset"）。
  - `_preview_music` 增加导入分支：源文件存在、`analysis.source_hash` 与当前源文件哈希一致、`load_timeline` 能加载才返回 `HtmlPreviewMusic(url=<music/audio 地址>?v=<源哈希>, gain=1.0, offset=<有效区间起点>)`，否则 `None`（与合成形态同一标准）。有效区间起点从 `timeline.imported` 的同一函数取，**不在这里重算规则**。`html_preview_meta_endpoint` 对 `music_source == "import"` 调用新分支。合成形态 `offset` 恒为 0，既有断言不变。
- **测试**（先写）：AC3：有 `range` 与无 `range`（后者区间起点 = 第一段起点）的 `offset` 值；增益 1.0；地址带源哈希；源文件被换（哈希不符）为 `None`；未分析为 `None`；合成形态响应只多一个 `offset: 0.0`。
- **完成标准**：AC3 满足。
- **验证命令**：`cd backend && uv run pytest tests/api/test_html_preview.py -q`；`make check`

### T4：`mix.py` 的 `source_start`（完成）

- **目标**：混音能从源文件的某一秒起截取配乐。
- **涉及文件**：`backend/src/studio/engines/render/mix.py`、`backend/tests/engines/test_mix.py`、`docs/references/ffmpeg.md`
- **接口与要点**：
  - `AudioTrack` 增加 `source_start: float = 0.0`（"从文件的这一秒起读"；旁白轨恒为 0，不受影响）。`_music_chain` 在 `atrim=end=` 之前按 `source_start` 截取起点（`atrim=start=<source_start>,asetpts=PTS-STARTPTS` 或在输入处加 `-ss`，**二选一以实测为准**：用已知音调的音频验证截取起点是否精确到毫秒，把结论与选择写进 `docs/references/ffmpeg.md`，注明日期与来源"实测"）。`source_start == 0` 时生成的命令与现在逐字节一致（保护既有用例）。
  - 新增命名常量 `MV_FADE_IN = 0.015`、`MV_FADE_OUT = 0.015`（设计 §2：先用 15 ms，冒烟听了再定），以及 `def music_video_mix(path: Path, source_start: float) -> MusicMix`（无旁白，无侧链，增益 0 dB）。
  - 总时长、`apad`、`atrim` 的"两端有限"约束不变；源文件比"区间终点"短时补静音到总长（既有行为）。
- **测试**（先写）：`build_mix_command` 的命令（`source_start > 0` 与 `= 0` 两种）；真实 ffmpeg：生成 440 Hz 与 880 Hz 各 2 秒拼接的 wav，`source_start=2` 时成片音轨的主频是 880 Hz（用现有测试里的探测/响度辅助函数，或 numpy FFT 读解码后的音轨）；淡出起点在 `duration - fade_out`；源文件短于总长时补静音且总长精确；`source_start` 超过文件长度时的行为（报 `MixError` 或全静音，**以 ffmpeg 实测为准并在测试里固定**）。
- **完成标准**：AC4 满足。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_mix.py -q`；`make check`

### T5：`worker_html` 的导入分支（完成）

- **目标**：渲染成片时用上传的歌做音轨，并保证混进成片的就是被检查过的那份字节。
- **涉及文件**：`backend/src/studio/worker_html.py`、`backend/src/studio/worker.py`（若有对 `import` 的拒绝或透传）、`backend/src/studio/api/jobs.py`（先 `grep -rn "music_source"` 确认成片入口是否还在别处拒绝 `import`）；测试 `backend/tests/test_worker_html_music.py`、`backend/tests/api/test_html_final_flow.py`
- **接口与要点**：
  - 删掉 `_run_html_job` 里对 `import` 的 `HtmlJobError`。`_music_source` 拆成按形态的两个函数：保留合成的 `_synth_score(...)`（行为不变），新增 `_import_score(workdir, errors, scratch) -> _Score | None`：`find_source(workdir/"music")` 缺失报"还没有上传音乐"；`analysis.json`、`sections.json` 缺失/损坏分别报"需要在配乐阶段分析/写段落"；把源文件复制到 `.cache/tmp/mix-<uuid8>/source.<ext>`（复用 `_copy_with_hash`，目录登记进 `scratch`），拷贝的哈希与 `analysis.source_hash` 不一致报"源文件已更换，需要在配乐阶段重新分析"。`_Score` 增加 `source_start: float = 0.0`。
  - 有效区间起点从已加载的时间轴来源取（`timeline.imported` 的同一函数，不在 worker 里重算规则）；`_music_mix` 对导入形态返回 `music_video_mix(score.path, score.source_start)`。
  - 缓存键 `_cache_key` 的组成里，导入形态加入源哈希与区间；合成形态与讲解的缓存键保持原样（既有缓存不失效）。`ENGINE_VERSION` 不动（出帧逻辑没变）。
  - `final.json`：导入形态增加 `"audio_sources": {..., "music": {"hash": <源哈希>, "range": [start, end]}}`（旁白形态的 `audio_sources` 现有结构不变，导入形态没有旁白，`audio_sources` 只含 `music` 键）；仍写 `music_hash`？**不写**——导入形态用 `audio_sources.music`，合成形态保持 `music_hash`；`api` 或前端若有读取 `music_hash` 的地方先 grep 确认不受影响。
- **测试**（先写）：AC5 各条，沿用该测试文件的 `FakeBackend` 与夹具风格（新增一个 `mv` 夹具：合成歌曲 + `analysis.json` + `sections.json` + `beatsheet` + 极简场景）；缺文件各给一条用例；检查之后源文件被换（在 fake backend 的 `render_video` 回调里改写原文件）→ 混音用的仍是拷贝、`final.json` 记录的哈希是拷贝的哈希；缓存键随区间与源哈希变化；真实 ffmpeg 的一条（标记 `slow` 的沿用现有约定）：渲染极小 MV，成片音轨时长等于时间轴时长；合成短片/讲解的既有用例全部不变。
- **完成标准**：AC5 满足。
- **验证命令**：`cd backend && uv run pytest tests/test_worker_html_music.py tests/api/test_html_final_flow.py -q`；`make check`

### T6：前端的上传请求、类型与查询（完成）

- **目标**：前端能上传文件、读到新的 meta 字段，类型检查通过。
- **涉及文件**：`frontend/src/api/http.ts`、`frontend/src/api/endpoints.ts`、`frontend/src/types/api.ts`、`frontend/src/composables/queries.ts`、`frontend/src/test/`（现有的夹具）；测试 `frontend/src/api/http.spec.ts`（若无则新建）、`frontend/src/api/endpoints.spec.ts`、`frontend/src/composables/queries.spec.ts`
- **接口与要点**：
  - `http.ts`：新增 `uploadForm<T>(path, form: FormData, options?: { onProgress?: (loaded: number, total: number) => void; signal?: AbortSignal }): Promise<T>`，用 `XMLHttpRequest` 取上传进度（`fetch` 没有上传进度）；非 2xx 抛与 `request` 相同的 `ApiError`（沿用 `parseErrorDetail` 的解析规则）；不设 `Content-Type`（浏览器带 boundary）；`signal` 触发 `abort()`。
  - `types/api.ts`：与后端对应的 `MusicSourceOut`、`MusicSourceInfo`、`MusicAnalysisOut`、`MusicGridOut`、`MusicRangeOut`、`MusicEnergyOut`、`SectionsCheckOut`；`MusicMetaOut` 增加 `form` 与可选字段；`HtmlPreviewMusic` 增加 `offset: number`。
  - `endpoints.ts`：`uploadMusicSource(projectId, file, options?)`；`musicAudioUrl` 保持不变（导入形态地址由 meta 的 `hash` 作版本）。
  - `queries.ts`：`useUploadMusicSourceMutation(projectId)`，成功后 `invalidate` `musicMeta`、预览 meta 与项目的阶段状态（沿用 `queries.ts` 中其他变更用的失效列表，约在 213、786 行附近）；上传进度由调用方传 `onProgress`，不进查询缓存。
- **测试**（先写）：`uploadForm` 用假的 `XMLHttpRequest`（`vi.stubGlobal`）验证：进度回调、2xx 解析 JSON、422 的 `ApiError.detail`、`abort`；端点的 URL 与方法；变更成功后三个查询被失效。
- **完成标准**：类型、lint、单测全部通过。
- **验证命令**：`cd frontend && pnpm exec vitest run src/api src/composables`；`make check`

### T7：导入形态的音乐画布（完成）

- **目标**：用户能上传歌曲，并看到能量曲线、网格、段落、区间与分析摘要。
- **涉及文件**：新建 `frontend/src/features/canvas/music/importView.ts`、`SourceUploader.vue`、`EnergyView.vue`、`ImportMusicCanvas.vue`、`AnalysisSummary.vue`；修改 `frontend/src/pages/ProjectWorkbenchPage.vue`（`stage === 'music'` 且项目 `music_source === 'import'` 时渲染 `ImportMusicCanvas`，插槽 `actions` 与 `MusicCanvas` 一致）、`frontend/src/features/canvas/stageActions.ts`（若有按形态的差异，先读）；测试同名 `.spec.ts`
- **接口与要点**：
  - `importView.ts`（纯函数，不碰 DOM）：`gridLines(grid: MusicGridOut, range: MusicRangeOut | null, duration: number, width: number): { x: number; strong: boolean }[]`（拍线细、强拍线粗，只画区间内的；拍线过密时按像素间隔抽稀）、`energyBars(energy: MusicEnergyOut, width: number, height: number)`（复用 `waveform.ts` 的 `timeToX`/`xToTime`）、`sectionBandsFromMeta`（复用 `sectionBands`）、`rangeMask(range, duration, width)`、`analysisRows(meta)`（BPM、置信度、拟合残差、时长、警告的文案行；置信度 < 0.5 或有警告时标记为需要注意）。**坐标换算一律以"整曲时间"为轴**（能量曲线与网格取整曲，区间与段落作为叠加层）。
  - `SourceUploader.vue`：`<input type="file" accept=".mp3,.wav,.m4a,.flac,.ogg">` 加拖拽；客户端先挡扩展名与 150 MB（给出中文提示，但不当作唯一校验——服务端为准）；上传中显示进度条与"取消"；成功后触发查询失效；422/409 显示服务端的中文原因；`busy`（有一轮在跑）时禁用并说明。已上传时是"更换歌曲"入口并提示"更换后需要让 agent 重新分析"。
  - `ImportMusicCanvas.vue`：用 `useMusicMetaQuery`；未上传 → 上传区；已上传 → 左侧 `<audio controls>` + `EnergyView`（SVG，叠加网格线、段落色块与标签、区间遮罩与当前播放位置，点击/拖动跳转 `audio.currentTime`），右侧 `AnalysisSummary`（分析摘要、`sections_check` 的错误与警告、stale 提示"源文件已更换，请让 agent 重新分析"、未分析时的空状态"让 agent 调用 analyze_music"）。不含脚本与事件标签；沿用 `MusicCanvas` 的 `actions` 插槽与 `data-testid` 命名风格（`music-*`）。
  - 样式沿用现有组件的 tailwind 与 shadcn-vue 组件；不引入新依赖。
- **测试**（先写）：`importView` 纯函数的精确断言（拍线抽稀、区间内过滤、遮罩坐标、边界：区间从 0 开始/到曲末、`range` 为空）；`SourceUploader` 的状态机（空闲→上传中→成功/失败/取消，客户端挡超大与错误扩展名，`busy` 禁用，进度更新）；`ImportMusicCanvas` 的分流（未上传/已上传未分析/已分析/校验有错/stale 各自的可见元素，用 `data-testid` 断言）；点击能量曲线更新 `audio.currentTime`。
- **完成标准**：AC6 中画布部分满足；`ProjectWorkbenchPage` 对合成形态与其他阶段的行为不变（既有页面测试通过）。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/canvas/music src/pages`；`make check`

### T8：预览按 `offset` 同步导入音乐（完成）

- **目标**：拖动、暂停、循环、换源时，预览画面与导入音乐保持对齐。
- **涉及文件**：`frontend/src/features/canvas/animation/htmlPreview/useHtmlPlayback.ts`、`previewClock.ts`；测试 `useHtmlPlayback.spec.ts`、`previewClock.spec.ts`
- **接口与要点**：
  - 预览时间 `t` 与音乐元素时间 `a` 的关系是 `a = t + music.offset`。`useHtmlPlayback.ts` 中把配乐 `currentTime` 当作时间的 4 处（`startScore` 的比较与赋值、`syncScore` 换源时的赋值与跟随旁白的纠正、`musicClockTime(score.currentTime, ...)` 取时钟）全部改成经由两个小函数 `toScoreTime(t, meta)` 与 `fromScoreTime(a, meta)`（放进 `previewClock.ts`，纯函数，`offset` 缺省为 0）。`musicClockTime(audioTime, duration)` 的签名保持不变，调用方传 `fromScoreTime(...)` 的结果。
  - `offset == 0` 时行为必须与现在逐点一致（合成形态不回归）。
  - 音乐播到区间终点（`a ≥ offset + duration`）时与现在播到 `duration` 的处理一致：钳在 `duration`，不继续推进。
- **测试**（先写）：`toScoreTime`/`fromScoreTime` 往返与 `offset=0` 恒等；在 `useHtmlPlayback.spec.ts` 里用现有的假音频，覆盖：`offset>0` 起播时 `currentTime` 被设为 `at + offset`；拖动时间轴；暂停/继续；循环回到起点；音乐源地址变化（换歌）后接着放；时钟取值扣掉 `offset`；既有用例全部不变。
- **完成标准**：AC6 中预览部分满足。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/canvas/animation/htmlPreview`；`make check`

### T9：放开音乐 MV 入口（完成）

- **目标**：用户能在创建项目对话框里选择并创建音乐 MV 项目。
- **涉及文件**：`backend/src/studio/api/video_kinds.py`、`backend/tests/api/test_video_kinds.py`、`backend/tests/api/conftest.py`（若夹具里有"导入不可用"的假设）、`frontend/src/test/videoKindsFixture.ts`、`frontend/src/components/VideoKindPicker.spec.ts`、`frontend/src/features/ideas/CreateProjectDialog.spec.ts`、`docs/design/2026-10-05-import-music-mv-4b.md`（无需改）
- **接口与要点**：
  - `unavailable_reason(...)`：删掉 `music_source == "import"` 的"尚未实现"分支与相应文案；`music_source == "import"` 与其他形态一样，只在流水线里有未注册阶段时不可用（4A 已注册 `concept`、`music`、`beatsheet`、`animation_html`）；`engine == "manim"` 加配乐不可用的规则不变。同步更新 `stage` 注册检查所在的 docstring。
  - 测试里依赖"导入不可用"的断言（`test_default_registry_everything_but_imported_music_is_available`、`unavailable_reason(["animation_html"], registry, "import")` 那条）改成新行为：默认注册表下四种预设全部可用；流水线缺阶段时仍按原规则给出原因。前端夹具里把音乐 MV 预设的 `available` 改为 `true`，并补一条"选中音乐 MV 后创建项目的请求体带 `music_source: 'import'`"的断言。
- **完成标准**：AC7 满足。
- **验证命令**：`cd backend && uv run pytest tests/api/test_video_kinds.py -q`；`cd frontend && pnpm exec vitest run src/components src/features/ideas`；`make check`

### T10：真实冒烟、文档与收尾（完成）

- **目标**：用真实歌曲走通整条链路，把读数与结论写进文档。
- **涉及文件**：新建 `backend/tests/smoke/test_music_video_smoke.py`（沿用 `tests/smoke/support.py` 的 `build_harness`/`record_evidence` 约定与 `pytestmark = pytest.mark.smoke`）、`docs/references/import-music-mv.md`、`docs/references/README.md`、`docs/quality/QUALITY.md`、`docs/quality/tech-debt.md`（4A 终审遗留项与本计划新增项）、`docs/glossary.md`、`docs/ARCHITECTURE.md`、`docs/plans/TODO.md`（不在本任务里改，见决策记录）、本计划
- **接口与要点**：
  - 冒烟用例：歌曲路径取环境变量 `MV_SMOKE_SONG`，缺省为仓库内 `docs/temp/海阔天空.mp3`；文件不存在则 `skip`（不报错）；**不复制、不提交歌曲**；用本地 Claude 登录（`claude-login`，沿用已有的冒烟配置与"不限次数"的约定，见记忆中的冒烟政策）。步骤：创建 `music_video` 项目 → 通过上传端点上传 → 依次驱动 `concept`、`music`（agent 调 `analyze_music`、写 `sections.json`、`validate_sections`）、`beatsheet`、`animation_html`，每个阶段定稿 → 渲染成片。把每阶段的轮次摘要、拟合读数（BPM、置信度、残差、候选边界）、出帧耗时、成片大小与时长、`ffprobe` 的音轨信息写进 evidence 目录。
  - 控制者（不是 subagent）运行冒烟与 L4 浏览器验证；强拍相位与段落由负责人试听核对，结论回填 `docs/references/import-music-mv.md`（日期、来源"实测"、歌曲只写文件名与时长，不写歌词或其他受版权保护的内容）。淡入淡出 15 ms 是否生硬也在这一步由人耳判断，需要时只改 `MV_FADE_IN`/`MV_FADE_OUT` 两个常量。
  - 文档：QUALITY 的 `engines.audio`、`stages.music`、`api` 行补 4B 的已知缺口（强拍相位与 BPM 只有一首歌的读数；淡入淡出；整曲出帧耗时）；tech-debt 登记 4A 终审遗留项里仍未处理的（`timeline/load.py` 的 `_source_file` glob 与 `find_source` 规则对齐、`music` 定稿时拦截多个源文件——**若 T1 的上传只留一个源文件，则多源文件已不可能出现，登记为"仅手工放文件时才可能"**）；glossary、ARCHITECTURE 的模块行补 `music_import`、`probe`、`source_start`。
- **完成标准**：AC8、AC9 有证据；`make check` 全绿；计划的「进度」「验证记录」写完，状态改为待验收。
- **验证命令**：`make check`；`make smoke`（只跑新用例：`cd backend && uv run pytest tests/smoke/test_music_video_smoke.py -m smoke -q`，需要本地 Claude 登录）

## Review Focus

以下是设计隐含、但没有任务专门测试的最可能咬到真实用户的输入，每条都已落到对应任务的测试里：

1. **假扩展名、零字节、超大、含路径成分与中文的文件名**：上传必须只信内容探测与白名单，文件名不参与路径拼接，失败不留残留（T1）。
2. **上传进行中又开了一轮 agent，或同时两次上传**：应 409，不能交错写出半个文件（T1）。
3. **换歌之后留下旧的 `analysis.json`/`sections.json`**：meta 标 stale、预览不放旧音、成片拒绝并提示重新分析，而不是用旧段落切新歌（T2、T3、T5）。
4. **预览里拖动、暂停、循环、换源时的音画错位**：`offset` 在每个用到音乐时间的地方都要换算，`offset=0` 不能回归（T8）。
5. **源文件比区间终点短、或 `source_start` 越界**：成片时长仍精确等于时间轴时长，不卡死、不产出半成品（T4、T5）。

## 进度

- 2026-10-05：T1–T10 全部完成（native 执行）。`make check` 全绿；真实冒烟通过（约 1005 秒）；L4 浏览器验证通过。
- 提交：T1 `c09feb9`、T2–T9 见 `git log import-music-4b`；T10 冒烟用例与文档收尾。
- 2026-10-06：负责人看了成片，反馈“效果一般，需通过对话和风格库控制画面”；强拍相位/BPM/淡出的试听核对留到系统使用时。原待办：试听 `data/evidence/import-music/smoke/music-video-final.mp4`，核对强拍相位、BPM（76.9 还是 153.9）、段落边界与截断处淡出，结论回填 `docs/references/import-music-mv.md`。

## 下一步

- 无（已归档）。后续：负责人系统使用后提出音乐 MV 画面质量的需求（见 TODO P2）。

## 决策记录

- 2026-10-05 — `music/meta` 导入形态的 `source.duration` 只在 `analysis.source_hash` 与当前源文件一致时取分析里的时长，否则为 `None`——设计 §3.2 写了"源文件（文件名、大小、哈希、时长）"，但每次 meta 请求都跑一次 `ffprobe` 代价不值；上传响应本身带 `duration`，前端在上传成功后可直接使用，meta 不重复探测。
- 2026-10-05 — `api/music_import.py` 单独成文件，`music.py` 只做形态分流 — `music.py` 已约 200 行，导入形态的上传、meta 构建、音频解析另放，职责清楚。
- 2026-10-05 — 导入形态的画布不并入 `MusicCanvas.vue`，由页面按项目的 `music_source` 分流到 `ImportMusicCanvas.vue` — 两种形态的标签与数据完全不同，合并会让合成形态的组件和测试变复杂；项目设置在页面里已有，不必等 meta。
- 2026-10-05 — 上传进度用 `XMLHttpRequest` — `fetch` 没有上传进度，设计 §4 要求显示进度。
- 2026-10-05（执行中）— `build_import_meta` 放 `api/music_import_meta.py`，不放 `music_import.py`（避免 `music` ↔ `music_import` 循环 import）；新增公开的 `timeline.imported.effective_range` 作为预览、成片与 meta 共用的区间规则。
- 2026-10-05（执行中）— 导入音乐只对 `(html, 无旁白)` 放开：计划写"不再阻止 import"，但 `load_timeline` 对旁白加导入直接报错，放开会让用户建出渲染不了的项目；其余两种组合保持不可用，原因文案「「配乐（导入音乐）」目前只支持无旁白的 HTML 音乐视频」（含"配乐"，既有测试依赖）。`unavailable_reason` 增加可选的 `narration` 参数。
- 2026-10-05（执行中）— 混音取源文件起点用滤镜 `atrim=start`（不用输入端 `-ss`）：实测毫秒级精确；`source_start` 超出文件长度时不报错，输出全静音、总长精确（测试固定）。
- 2026-10-05（执行中）— 冒烟环境变量用 `STUDIO_SMOKE_SONG`（不是计划里的 `MV_SMOKE_SONG`）：`make smoke` 只放行 `STUDIO_*` 变量；冒烟在 `probe_audio` 之后把歌拷进 `music/source.<ext>`，不经 HTTP 上传端点（端点由 api 测试覆盖）。
- 2026-10-05 — T10 不改 `docs/plans/TODO.md` — 沿用 4A 收尾的做法，TODO 由负责人确认后在收尾步骤更新。

## 意外与发现

- 流式解析：Starlette 的 `UploadFile` 在进入端点前就把整个文件落盘，无法按上限中途中止，改用 `python_multipart` 的流式解析器（references 已记）。
- 缓存键不用改：MV 的时间轴哈希（`sha256(timeline + source_hash + range)`）本来就进了 `_cache_key`，测试固定了这一点。
- `worker` 不能 import `stages`（import-linter）：源文件路径取自时间轴的 `music.file`，区间与源哈希加进 `LoadedTimeline`（`range`、`source_hash`，默认 `None`）。
- 讲解（有旁白）加导入音乐的组合时间轴读取不支持，所以入口只对无旁白的 HTML 音乐视频放开（见决策）。
- 终审的 9 条 Minor 也已全部处理（畸形请求体 422、part 完整性、mkdir 失败不锁项目、坏 energy 降级、取消在传完后不可用、上传提示常驻、换源加换 offset 不跳、源文件消失报重新分析、断开用例去掉 noqa 并补四类上传测试）。
- 终审（opus）发现并修复两处：multipart 头部被读块边界截断时解析失败（现累加分段、在 `on_header_end` 落定，补分块请求测试）；上传期间开始新一轮会让一轮结束时的写入范围检查静默还原上传（现 `messages`/`continue` 端点在项目上传中返回 409）。
- 冒烟里 agent 把前奏单列为一个段落并从 1.41 秒起；候选边界 11 个、段落边界 9 个，整曲区间不写 `range`。

## 阻塞

- 无

## 验证记录

- `make check`（2026-10-05，T9 之后）：后端 2626 passed（97 deselected 为 `slow`/`smoke`），前端 1121 passed，lint、类型检查、import-linter（25 条契约）、文档检查全部通过。
- `slow` 用例（真实 Chromium + ffmpeg）：`tests/engines/test_mix.py`、`tests/test_worker_html_music.py`（含音乐 MV 真实成片）、`tests/test_worker_html.py`、`tests/api/test_html_final_flow.py` 全部通过。
- 真实冒烟：`cd backend && uv run pytest tests/smoke/test_music_video_smoke.py -m smoke`，1 passed，1004.7 秒；读数与耗时见 `docs/references/import-music-mv.md`。
- L4 浏览器（内置浏览器，隔离的 api:8011 + 临时数据目录）：上传区上传 wav 成功（进度、更换入口）；能量曲线叠加 9 条强拍线与 24 条拍线（区间内）、段落名、区间外遮罩（25/825）、置信度 0.42 与警告标橙、`sections_check` 错误逐条显示；点击能量曲线把 `audio.currentTime` 设到约 10 秒、播放头 499.9；预览 meta 的 `offset` 为 4.5，播放时音频时间减 4.5 与时钟一致，拖动后音频跳到 `offset + t`。
- 变异检查：T7 组件先写后测，改坏两处（stale 仍显示旧摘要、busy 不禁用）后对应用例变红，恢复后全绿。
