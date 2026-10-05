# 子项目 4B：上传、画布、预览与成片（导入音乐与音乐 MV）

状态：待批准（2026-10-05）。本文是 [导入音乐与音乐 MV 设计](2026-10-05-import-music-mv.md)（以下简称"4 设计"）§7、§8 的实现级补充，只写 4 设计没有回答的决定和落到具体文件的接口；4 设计与总设计的其余部分不变。4A（agent 侧）已完成，见 [import-music-4a](../plans/completed/import-music-4a.md)。

## 1. 目标与范围

**交付**：用户在「音乐 MV」项目里上传一首歌，在音乐画布上看到波形与段落，在画面预览里听到按截取区间对齐的原曲，渲染出音轨取自原曲的 MP4；创建音乐 MV 项目的入口正式开放。

**一份计划**（4B），后端先行、前端随后、最后冒烟与放开入口，沿用 3B 的做法。

**非目标**：画布内手改 `sections.json`（修改交给 agent，4 设计 §7）；歌词；变速曲；多首歌；在线音乐服务；4A 已记录的已知缺口（4 设计 §11）。

## 2. 已确认的决定

| 项 | 决定 | 依据 |
|---|---|---|
| 冒烟素材 | 负责人提供的一首真实歌曲，放在本机 `docs/temp/海阔天空.mp3`（已被 `.gitignore` 忽略，不入库）；自动化测试仍只用合成夹具 | 2026-10-05 负责人确认 |
| 摸底读数 | 对该歌曲跑 4A 的 `analyze_song`：76.9 BPM、置信度 0.84、拟合残差 14 ms、无警告；强拍相位与 BPM 是否正确未经人工核对 | 2026-10-05 实测，用于设计参考，不是验收 |
| 波形 | 画布用 `analysis.energy`（能量曲线）代替合成形态的 `waveform`，不改 `analysis.json` 结构 | 2026-10-05 设计讨论 |
| 画布编辑 | 只展示，不编辑 `sections.json` | 4 设计 §7 |
| 上传方式 | multipart（`python-multipart` 已在 `uv.lock`，不新增依赖） | 2026-10-05 |
| 淡入淡出 | 沿用 `mix.py` 的默认 15 ms（只防爆音），写成命名常量 `MV_FADE_IN`/`MV_FADE_OUT`；冒烟时人耳判断截断处是否生硬，需要时只改常量 | 2026-10-05 设计讨论 |

## 3. 后端

### 3.1 上传端点

`POST /api/projects/{id}/music/source`（multipart，字段 `file`），位置 `backend/src/studio/api/music.py`（沿用本文件的路由与 `Depends` 写法）。

- 校验顺序与错误码：项目存在（404）；`music_source == "import"`（404 "这个项目没有导入音乐"）；项目当前没有运行中的一轮（409，沿用 `turn_runner.is_project_busy`）；扩展名在白名单 `SOURCE_EXTENSIONS`（4A 的 `stages.common.music_source`，422）；大小 ≤ `MAX_UPLOAD_BYTES = 150 MB`（边读边计数，超限立即中止，422）；用 `ffprobe` 确认是音频且时长在 5–600 秒（`song.MAX_SONG_SECONDS` 同值，422 并带中文原因）。
- 写入：先落到工作区的临时文件，校验通过后，在同一个调用里清掉旧的 `music/source.*`、再原子改名为 `music/source.<ext>`（4A 终审遗留：单一源文件）。路径只走工作区的安全解析。
- 换歌不删 `analysis.*` 与 `sections.json`：它们的 `source_hash` 与新源文件不一致，`music` 阶段的定稿条件与 `load_timeline` 已把这种状态当成 stale/阻塞，用户让 agent 重新分析即可。
- 响应：`{filename, size, sha256, duration}`；不触发分析（分析是 agent 工具的事，4 设计 §4）。

### 3.2 meta 与音频端点

- `GET .../music/meta` 泛化：响应增加 `form: "synth" | "import"`。导入形态返回：`source`（文件名、大小、哈希、时长；没有上传时为空）、`analysis`（BPM、置信度、拟合残差、警告；没有分析时为空）、`grid`（有效 bpm/offset 与强拍列表）、`sections`（来自 `sections.json`，缺失时为空）、`range`、`energy`（曲线与 `hop`）、`sections_check`（`validate_sections` 的错误与警告）、`stale`（`analysis.source_hash` 与当前源文件不一致）。合成形态的响应与行为不变。
- `GET .../music/audio` 在导入形态返回 `music/source.<ext>`，媒体类型按扩展名，`Range` 沿用；`Cache-Control: no-store`。
- 把 `_require_score_project` 改为按 `music_source` 分流（`synth` / `import`），其余非配乐项目仍 404。

### 3.3 预览（`api/html_preview.py`）

- `HtmlPreviewMusic` 增加 `offset: float = 0.0`（秒）：导入形态取有效截取区间起点，合成形态恒为 0。`gain` 导入形态为 1.0（无旁白不压低）。
- `_preview_music` 导入形态：源文件存在、`analysis.source_hash` 与当前文件一致、时间轴可加载才给预览用，否则 `music=None`，画面照常（与合成形态同一标准）。音频地址带 `source_hash` 作版本号。

### 3.4 成片（`worker_html.py`、`engines/render/mix.py`）

- 去掉 `worker_html.py` 里对 `import` 的拒绝。`_music_source` 增加导入分支：把源文件复制到 `.cache/tmp` 下的私有目录并边复制边算哈希（与合成形态同一套防"检查后又被换"的做法），哈希与 `analysis.source_hash` 比对，不一致就返回"源文件已更换，需要在配乐阶段重新分析"；缺 `analysis.json`/`sections.json` 同样给出明确原因。
- `mix.py`：`AudioTrack` 增加 `source_start: float = 0.0`（在输入端从文件的这一秒起读），`MusicMix` 的 MV 配置用 `MV_FADE_IN`/`MV_FADE_OUT`，无旁白也就无侧链。`atrim`、淡出起点都按成片时长算，补静音到总长的现有行为不变。
- 缓存键与 `final.json`：缓存键加入 `source_hash` 与有效区间；`final.json` 的 `audio_sources` 增加 `{"music": {"hash", "range"}}`（合成形态仍写现有的 `music_hash`）。
- 出帧时长：约 325 秒的歌，30 fps 约 9750 帧，**冒烟中实测**，结论写进 `docs/references/`（总设计 §12、4 设计 §8）。

### 3.5 放开入口（`api/video_kinds.py`）

去掉 `import` 的"阶段尚未实现"限制；`music_source == "import"` 现在要求流水线里的阶段都已注册（`concept`、`music`、`beatsheet`、`animation_html`，4A 已齐）。创建项目对话框里音乐 MV 预设由此可选，不改前端预设逻辑。同步更新 `tests` 里依赖"导入不可用"的断言。

## 4. 前端

位置 `frontend/src/features/canvas/music/`，沿用本目录现有的组件与 `queries.ts` 的写法。

- `MusicCanvas.vue` 按 meta 的 `form` 分流；合成形态的组件与测试不动。
- **上传区**（`SourceUploader.vue`）：未上传时显示，拖拽或选择文件，显示格式与大小限制、上传进度与错误（422/409 的中文原因）；已上传时改为"更换歌曲"入口，并提示"更换后需要让 agent 重新分析"。
- **导入形态的主体**：播放器 + 能量曲线（`WaveformView` 复用其绘制，输入换成 `energy`），叠加强拍线（细）、强拍线（粗）、段落色块、截取区间；点击段落或曲线跳转播放。右侧：分析摘要（BPM、置信度、残差、时长、警告）与 `sections_check` 的校验结果；stale 时显示醒目提示。
- **预览播放**（`htmlPreview/useHtmlPlayback.ts`、`previewClock.ts`）：音乐轨从 `music.offset` 起播，预览时间 t 对应音频 `offset + t`，拖动、暂停、循环时同步；`offset` 为 0 时与合成形态行为一致。
- 类型与端点：`types/api.ts`、`api/endpoints.ts`、`composables/queries.ts` 增加上传与新 meta 字段；前端对 `video-kinds` 的可用性来自接口，不写死。

## 5. 测试与验证

| 层 | 测什么 |
|---|---|
| api | 上传：白名单、大小上限（含恰好等于上限）、非音频内容、时长越界、非 `import` 项目、运行中的一轮（409）、换歌清掉旧 `source.*`、失败不留临时文件与旧文件；meta 各状态（未上传、已上传未分析、已分析、stale、`sections_check` 有错）；`audio` 的 `Range`；预览 `music.offset`（有 `range`/无 `range`/源文件被换） |
| worker | 导入分支：按区间截取，成片时长等于时间轴时长；源文件在检查后被换（哈希不符）报错；缺 `analysis.json`/`sections.json` 报明确原因；缓存键随 `source_hash` 与区间变化；`final.json` 记录；合成形态与讲解的既有用例不变 |
| mix | `source_start` 的 ffmpeg 命令与实际音轨内容（用已知音调的短音频验证截取起点）；淡出起点；补静音 |
| 前端 | 组件与组合式函数的 vitest：上传状态机、meta 分流、预览时钟的 offset 同步；视图的叠加层数据（强拍/段落/区间的坐标换算）用纯函数单测 |
| L4 浏览器 | 上传区、能量曲线与叠加、点击跳转、预览播放（由控制者在内置浏览器截图验证，沿用已有偏好） |
| 真实冒烟 | `docs/temp/海阔天空.mp3` 走完整条流水线并出成片（`make smoke`，默认不跑；本地 Claude 登录，不限次数）；记录出帧耗时、成片大小、拟合读数；**人工核对**强拍相位与段落是否合理（agent 听不到，需要负责人听） |

## 6. 对已批准设计的补充与修订

| 项 | 内容 |
|---|---|
| 4 设计 §7 | 补上传的校验顺序、`MAX_UPLOAD_BYTES = 150 MB`、`ffprobe` 校验、写入与清理旧源文件的方式；meta 的导入形态字段 |
| 4 设计 §8 | `AudioTrack.source_start`；`final.json` 的 `audio_sources` 的 MV 记法；淡入淡出的取值与待冒烟确认 |
| 子项目 3B 设计 | `HtmlPreviewMusic` 增加 `offset`；`api/music.py` 的配乐项目判断按 `music_source` 分流 |
| 总设计 §3.5 | 放开音乐 MV 预设（此前因 `import` 阶段未实现而禁用） |

## 7. 已知缺口

| 缺口 | 说明 |
|---|---|
| 强拍相位与 BPM 的正确性只有一首歌的读数，且需人工核对 | 4 设计 §11 的缺口仍在；冒烟后把这首歌的结论写进 `docs/references/` |
| 淡入淡出 15 ms，歌曲被截断处可能生硬 | 冒烟人耳判断后调常量 |
| 5 分钟以上成片的耗时与内存 | 冒烟实测，必要时另列优化项 |
| 画布不能直接改段落 | 有意如此（4 设计 §7）；若冒烟中发现修改成本高，再单独立项 |
