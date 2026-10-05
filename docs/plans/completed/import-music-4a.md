# import-music-4a：导入音乐与音乐 MV——agent 侧

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成（2026-10-05 验收，合并到 main） |
| 里程碑 | 多形态视频流水线·子项目 4（4A） |
| 设计依据 | [导入音乐与音乐 MV](../../design/2026-10-05-import-music-mv.md)（已批准 2026-10-05）；总设计 [§4、§6.2、§7.2](../../design/2026-10-04-html-video-pipeline.md) |
| 分支 | `import-music-4a` |
| 批准记录 | 2026-10-05：设计已批准；负责人批准计划，采用 subagent-driven 执行 |

## 目标

agent 能在「音乐 MV」项目里走完 `concept → music → beatsheet → animation_html`：对工作区里的 `music/source.*` 做分析，写出并校验 `sections.json`，按段落写 MV 版节拍脚本，再产出能读到 MV 时间轴的画面阶段。音频本计划用夹具文件放进工作区；上传、画布、预览播放、成片混音属于 4B。

## 范围

**包含：**

- `engines.audio`：`librosa` 依赖、歌曲分析（解码、拟合恒定网格、强拍相位、候选段落、能量曲线、置信度与拟合残差）、分析图、带超时与资源上限的隔离运行。
- `studio.timeline`：MV 来源（`music_source="import"`）的读取、`range` 截取、哈希。
- `music` 阶段：导入分支（工具 `analyze_music`、`validate_sections`；定稿条件；状态摘要；提示词）；与合成分支靠工作区内容分流。
- `beatsheet` 阶段：MV 版校验（`ref` 代替 `bars`、不允许 `bpm`）与提示词。
- `animation_html` 阶段：`prepare_turn` 与提示词认得 MV 时间轴；`env.energy` 取自导入分析，`hit/span` 无数据时不报错。
- 阶段层测试（fake 运行时跑通四阶段、stale 传递）；`docs/references/librosa.md`；`docs/quality/QUALITY.md` 的已知缺口。

**不包含：**

- 上传端点、音乐画布的导入形态、预览播放导入音频、worker 的截取与混音（4B）。
- `api/music.py`、`api/html_preview.py` 对导入形态的泛化（4B；4A 里它们对 `import` 项目保持现状）。
- 歌词、变速曲、真实歌曲的准确率实测（设计 §2、§11）。

## 验收标准

- [x] AC1：对已知 BPM、offset 的合成节拍音频，`analyze_song` 拟合 BPM 误差 < 0.5%、offset 误差 < 30 ms；散拍或变速音频置信度低且不抛异常；同一文件两次分析的 `analysis.json` 逐字节一致。（验证：`tests/engines/test_audio_song.py`）
- [x] AC2：`analyze_music` 工具对夹具歌曲写出 `music/analysis.json` 与 `analysis.png`，返回带图的结果；不可解码或静音文件返回明确错误且不写 `analysis.*`。（验证：`tests/stages/test_music_import_tools.py`）
- [x] AC3：`validate_sections` 能报出：段落重叠、乱序、不对齐强拍（并给出最近强拍）、越出音频、首尾或相邻段落有空隙、`range` 不对齐或不包含段落、`id` 重复或不合法。（验证：`tests/stages/test_validate_sections.py`）
- [x] AC4：`load_timeline(TimelineSources(..., music_source="import"))` 产出的 MV 时间轴：以 `range` 起点为 0；`sections.json` 的 `bpm`/`offset` 覆盖分析值；`moments` 的 `at` 正确换算；`music.energy` 按 `range` 截取；哈希随 `range`、网格、`source_hash` 变化。（验证：`tests/timeline/test_import_timeline.py`）
- [x] AC5：`music` 阶段在导入形态下：源文件换了或 `sections.json` 校验不通过即不可定稿；两种形态互不影响（合成形态的既有测试不改动全部通过）。（验证：`tests/stages/test_music_stage.py`、`tests/stages/test_music_import_stage.py`）
- [x] AC6：MV 版 `beatsheet`：`ref` 缺失、顺序不一致、遗漏段落、出现 `bpm`/`bars`、`at` 越出本段均报错；短片校验的既有测试不改动全部通过。（验证：`tests/stages/test_beatsheet_validate.py`）
- [x] AC7：`animation_html` 的 `prepare_turn` 在 MV 工作区写出带 `grid/sections/moments/music.energy` 的 `upstream/timeline.json`；上游缺失时写 `timeline.error.txt`。（验证：`tests/stages/test_animation_html_stage.py`）
- [x] AC8：fake 运行时跑通四阶段，每阶段定稿后下游走 stale；`make check` 全绿，import-linter 契约不变。（验证：`tests/stages/test_music_video_pipeline.py`、`make check`）

## 任务

### T1：依赖与歌曲分析核心——解码与网格拟合（完成）

- **目标**：加入 `librosa`，并实现 `analyze_song` 的前半：解码、检测拍点、拟合恒定网格。
- **涉及文件**：`backend/pyproject.toml`、`backend/uv.lock`、新建 `backend/src/studio/engines/audio/song.py`、`backend/tests/engines/test_audio_song.py`、`backend/tests/engines/audio_fixtures.py`（合成节拍音频生成器，T2/T3/后续任务共用）、`docs/references/librosa.md`、`docs/references/README.md`
- **接口与要点**：
  - 依赖 `librosa>=0.10,<1`；`make setup` 后记录安装耗时与首次 `import librosa` 耗时（numba 冷启动）写进 references。
  - `decode_song(path: Path, *, ffmpeg: str = "ffmpeg") -> Samples`：用 ffmpeg 转成 22050 Hz 单声道 PCM 再读（沿用仓库已有 ffmpeg 依赖，统一 mp3/m4a/flac/ogg/wav 的解码路径）；失败、静音（峰值 < 约 -60 dBFS）、短于 5 秒、长于 `MAX_SONG_SECONDS = 600` 都抛 `AudioError`，消息中文。
  - `fit_grid(beat_times: Sequence[float]) -> GridFit`：对拍点序号做线性最小二乘得 `bpm`、`offset`（第 0 拍时刻），先剔除残差过大的离群拍点再拟合；返回 `residual_ms`（拟合后拍点残差的 RMS）。`bpm` 超出 `studio.timeline` 的合理范围（60–200）时按倍频/半频折算到范围内，折算不了则抛 `AudioError`。
  - `engines` 不 import `timeline`（纯能力层只依赖 `config`），BPM 范围在 `song.py` 内定义同值常量，并在测试里断言两处一致。
  - 外部库的行为（`beat_track` 的返回、`load` 的重采样、numba 警告）以实测为准写进 `docs/references/librosa.md`，注明日期和来源。
- **测试**（先写）：`audio_fixtures.py` 提供 `click_track(bpm, offset, seconds, sr)`（每拍一个短促衰减噪声加低频底鼓，强拍更响）。断言：120/96/140 BPM、offset 0.08 s 的拟合误差在 AC1 范围；半频/倍频折算；`decode_song` 对静音、过短、损坏文件、不存在文件给出中文错误；`MAX_SONG_SECONDS` 边界。
- **完成标准**：上述测试通过，`docs/references/librosa.md` 有实测记录。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_audio_song.py -q`；`make check`

### T2：歌曲分析核心——强拍相位、候选段落、能量、置信度（完成）

- **目标**：补全 `analyze_song`，产出 `analysis.json` 的全部字段。
- **涉及文件**：`backend/src/studio/engines/audio/song.py`、`backend/src/studio/engines/audio/analysis.py`（把 `_energy` 对外公开为 `energy_curve`，沿用 `ENERGY_HOP`，原调用点同步改名）、`backend/tests/engines/test_audio_song.py`
- **接口与要点**：
  - `SongAnalysis`（dataclass，`to_document() -> dict` 输出 `analysis.json` 的结构）：`source_hash`、`duration`、`bpm`、`offset`（**第一个强拍的时刻**，落在 `[0, 一小节)`）、`residual_ms`、`confidence`（0–1）、`beats`、`downbeats`（均为覆盖全曲的全局秒，按 4/4）、`candidates`（候选段落边界，已吸附到最近强拍，列表升序去重）、`hop`、`energy`（[0,1]）、`warnings`（中文提示）。
  - 强拍相位：四种相位里取"各拍位置的低频起音强度之和"最大者。
  - 候选边界：`librosa.segment.agglomerative` 对 MFCC 与色度的拼接特征分段，段数取 `round(duration / 20)` 夹在 [2, 12]，边界吸附强拍。
  - 置信度：`max(0, 1 − residual_ms / (0.15 × 拍长毫秒))` 乘以"检测到的拍数 ÷ 理论拍数"的覆盖率；低于 0.5 时在 `warnings` 里写"拍点不稳（可能是散拍或变速），请手动修正 sections.json 的 bpm/offset"。
  - 全部随机性固定种子；同一输入两次 `to_document()` 序列化后逐字节一致（浮点统一四舍五入到 6 位，沿用 `timeline_hash` 的做法）。
- **测试**（先写）：已知 BPM/offset 的 `analysis` 全字段（含 `downbeats` 间隔 = 4 拍、强拍相位在底鼓更响的位置）；`candidates` 都是强拍且升序；用"前 8 小节稀疏、后 8 小节密集"的合成音频，能量曲线后段高于前段；散拍（随机间隔）与变速（BPM 线性漂移 15%）置信度 < 0.5 且 `warnings` 非空；重复分析一致；`energy` 的 `hop`/长度与 `duration` 匹配。
- **完成标准**：AC1 全部满足。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_audio_song.py tests/engines/test_audio_analysis.py -q`；`make check`

### T3：分析图与隔离运行（完成）

- **目标**：画 `analysis.png`，并让分析在子进程里带超时与资源上限运行。
- **涉及文件**：`backend/src/studio/engines/audio/picture.py`（新增 `render_song_png`，复用谱图与波形绘制）、新建 `backend/src/studio/engines/audio/song_job.py`、`backend/src/studio/engines/audio/runner.py`（把 `_limited` 公开为 `limited_argv`，原调用点同步改）、`backend/tests/engines/test_audio_picture.py`、`backend/tests/engines/test_audio_song_job.py`
- **接口与要点**：
  - `render_song_png(analysis: SongAnalysis, samples: Samples) -> bytes`：波形 + 谱图 + 能量三行，叠加拍线（细）、强拍线（粗）和候选边界（橙）；文字只用 ASCII。
  - `song_job.py`：`async run_song_analysis(source: Path, out_dir: Path, *, timeout: float = 120.0) -> SongJobResult`，用 `python -m studio.engines.audio.song_job <source> <out_dir>` 子进程运行，产物（`analysis.json`、`analysis.png`）先写进临时目录，成功后由调用方移入 `music/`；超时、非零退出、缺产物都返回带 stderr 末尾若干行的中文错误；沿用 `runner.py` 的进程组清理与 CPU/内存限制。
  - 这是我们自己的代码，不走 Seatbelt（设计 §2）；子进程只读源文件、只写 `out_dir`。
- **测试**（先写）：分析图尺寸与非空（沿用既有 picture 测试写法）；`run_song_analysis` 对合成夹具成功、对静音夹具返回错误且 `out_dir` 无产物、对被杀超时的桩（`timeout` 极小）返回超时错误且不留进程。
- **完成标准**：隔离运行可复用于 T5 的工具与 4B 的 api。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_audio_picture.py tests/engines/test_audio_song_job.py -q`；`make check`

### T4：时间轴的 MV 来源（完成）

- **目标**：`studio.timeline` 能从 `analysis.json`、`sections.json`、`beatsheet.json` 构建 MV 时间轴并算出哈希。
- **涉及文件**：`backend/src/studio/timeline/build.py`、新建 `backend/src/studio/timeline/imported.py`、`backend/src/studio/timeline/load.py`、`backend/src/studio/timeline/__init__.py`、`backend/tests/timeline/test_import_timeline.py`、`backend/tests/timeline/test_load.py`
- **接口与要点**：
  - `build.py`：新增 `TimedSectionInput(id, label, start, end)`；`TimelineLayers` 增加 `timed_sections: list[TimedSectionInput] | None`（与 `sections`、`narration` 三选一，同时给出即 `TimelineError`）；`MusicInput` 增加 `file: str | None = None`，未给则沿用 `MUSIC_FILE`；`build_timeline` 对 `timed_sections` 直接使用起止，`duration` 取最后一段的 `end`，校验 id 合法唯一、段落首尾相接、`start < end`。
  - `imported.py`（纯函数，只依赖标准库）：`effective_grid(analysis: dict, sections_doc: dict) -> tuple[float, float]`（`sections.json` 的 `bpm`/`offset` 优先，否则取分析值）；`downbeat_times(bpm, offset, duration) -> list[float]`；`layers_from_import(analysis, sections_doc, beatsheet | None) -> ImportLayers`，包含 `TimelineLayers` 与 `source_hash`、`range`、`source_file`。有效截取区间（显式 `range`，缺省取段落跨度）起点为 0 重排：段落与时刻整体平移，网格的 `offset` 取"`range` 起点之后第一个强拍相对起点的秒数"（`range` 起点本身是强拍时为 0）；`music.energy` 按 `range` 与 `hop` 截取；`events` 为空。
  - `load.py`：`TimelineSources.music_source == "import"` 且 `narration=False` 时读 `music/analysis.json`、`music/sections.json`、`beatsheet/beatsheet.json`（`with_music=False` 时不含 `music` 层，且 `beatsheet` 可缺失，用于 beatsheet 阶段自己校验）；`LoadedTimeline.hash` 为 `sha256(timeline_hash + source_hash + range)`，`base_hash` 与 `hash` 相同；文件缺失、损坏、各层不一致统一汇总成 `TimelineError`。`music_source == "import"` 且 `narration=True` 不支持，抛 `TimelineError`。
  - 时间轴 schema 不改字段。
- **测试**（先写）：无 `range`；有 `range`（起点平移、段落被裁、能量截取长度 = `range` 时长 ÷ `hop`）；覆盖 `bpm`/`offset`；`beatsheet` 的 `at` 换算正确，越界报错；`ref` 指向不存在的段落报错；改 `range`、`bpm`、`source_hash` 哈希变，改不影响时间轴的字段（如 `label` 之外的无关键）哈希不变；`TimelineError` 汇总多条；既有 `test_load.py`、`test_build*.py` 不改动全部通过；import-linter 契约（timeline 不依赖其他 studio 模块）通过。
- **完成标准**：AC4 满足。
- **验证命令**：`cd backend && uv run pytest tests/timeline -q`；`make check`

### T5：`analyze_music` 与 `validate_sections` 工具（完成）

- **目标**：导入形态的两个 agent 工具，以及 `sections.json` 的校验逻辑。
- **涉及文件**：新建 `backend/src/studio/stages/music/analyze.py`、`backend/src/studio/stages/music/validate_sections.py`、`backend/tests/stages/test_music_import_tools.py`、`backend/tests/stages/test_validate_sections.py`、`backend/tests/fixtures/import_music/`（由 `audio_fixtures` 生成的短夹具，生成脚本入库，音频不入库）
- **接口与要点**：
  - `ANALYZE_MUSIC_TOOL`（`stages={"music"}`，无参数）：找 `music/source.*`（白名单扩展名与 4B 一致：mp3、wav、m4a、flac、ogg）；无源文件返回错误"还没有上传音乐，请让用户在音乐画布上传"；调用 `run_song_analysis`；成功后把 `analysis.json`、`analysis.png` 移入 `music/` 并 `ctx.record_tool_write`；返回文本含 BPM、拟合残差、置信度、总时长、候选边界（强拍秒数）、`warnings`，附压缩后的分析图（沿用 `tool.compress_picture`）。失败不改 `music/` 里的旧产物。
  - `check_sections(doc, analysis) -> SectionsCheck`（`errors`、`warnings`、`ok`，沿用 `BeatsheetCheck` 的写法）：`doc` 结构 `{bpm?, offset?, range?{start,end}, sections[{id,label,start,end}]}`；用 `timeline.imported.effective_grid` 与 `downbeat_times` 判断对齐，容差 30 ms，错误信息附最近强拍；规则：id 合法唯一；`start<end`；有序不重叠；**首尾相接，且恰好覆盖有效截取区间**（有 `range` 时即 `range`；没有时取"第一段起点到最后一段终点"的跨度）——设计只写"不重叠"，空隙在这里一律报错，见决策记录；全部落在音频长度内；`range` 起止对齐强拍且包含全部段落；`bpm`/`offset` 若给出需为合理数字；`label` 为空给警告。
  - `VALIDATE_SECTIONS_TOOL`：读 `music/sections.json` 与 `music/analysis.json`，`analysis.json` 缺失返回"请先 analyze_music"。
  - 解析时对非字典、缺字段、类型错误一律转成错误条目，不抛异常。
- **测试**（先写）：`validate_sections` 逐条覆盖 AC3；浮点边界（`start` 比强拍早/晚 29 ms 通过、31 ms 报错）；`analyze_music` 成功（写入哈希进工具写入记录）、无源文件、静音夹具、重复调用对同一文件产物一致、失败时旧产物原样保留。
- **完成标准**：AC2、AC3 满足。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_music_import_tools.py tests/stages/test_validate_sections.py -q`；`make check`

### T6：`music` 阶段的导入分支与提示词（完成）

- **目标**：把 T5 的工具接进阶段，按工作区内容分流定稿条件、状态摘要和 `prepare_turn`，写导入形态的提示词。
- **涉及文件**：`backend/src/studio/stages/music/__init__.py`、`backend/src/studio/stages/music/sources.py`、`backend/src/studio/stages/music/prepare.py`、`backend/src/studio/stages/music/tool.py`、`backend/src/studio/stages/music/prompt.md`、`backend/tests/stages/test_music_import_stage.py`、`backend/tests/stages/test_music_stage.py`、`backend/tests/stages/test_music_prompt.py`
- **接口与要点**：
  - 分流依据：工作区里有 `music/source.<白名单扩展名>` 即导入形态（`sources.py` 新增 `import_source(workdir) -> Path | None`）。阶段拿不到项目设置，这是沿用 `infer_sources` 的做法（设计 §6.1）。
  - `tools()` 为超集：`render_music`、`analyze_music`、`validate_sections`、`suggest_upstream_change`。`render_music` 在导入形态下返回错误"导入形态不用合成脚本"；`analyze_music`/`validate_sections` 在合成形态（无源文件）下返回"这是合成形态"或"还没有上传音乐"的明确提示。
  - `write_scope`：可写增加 `music/sections.json`；托管增加 `music/source.*`（按各扩展名展开）。`WriteScope` 是否支持通配以现有实现为准；不支持就逐个扩展名列出。
  - `finalize_blockers`（导入形态）：`analysis.json` 缺失或其 `source_hash` 与当前源文件哈希不一致 → "源文件已更换，需要重新 analyze_music"；`sections.json` 缺失 → 列出；`check_sections` 的每条错误逐行列出。无源文件且无 `compose.py` 渲染记录时，阻塞信息改为中立文案："还没有配乐：合成形态请写 music/compose.py 并 render_music；导入形态请先上传歌曲"。合成形态的既有信息与行为不变。
  - `status_summary`（导入）："已分析：BPM {bpm}，{duration} 秒，置信度 {confidence}；{n} 个段落"；未分析为"未分析"；有源无 `sections.json` 为"已分析，待写 sections.json"。
  - `prepare_turn`：有源文件时只复制导入形态无需的东西——不生成 `upstream/timeline.json`，并清掉旧的 `timeline.json`/`timeline.error.txt`；无源文件时行为不变，但"缺少上游产物"文案补一句"音乐 MV 请先上传歌曲"。
  - `prompt.md`：在现有内容前加"先判断形态"一节（`music/source.*` 存在 = 导入形态；否则看有无 `upstream/timeline.json`）；新增"导入形态"一章，要点：先 `analyze_music`、看图与候选边界、写 `sections.json`（结构、起止对齐强拍、有意义的标签）、`validate_sections` 通过后再请用户确认；自动分段常不准，修正写在 `sections.json`（含 `range`、`bpm`/`offset` 覆盖），不改 `analysis.*`；置信度低或残差大的提示要如实转告用户；你听不到歌，不要对音色、情绪下判断，段落命名依据结构与能量曲线。合成章节保持原文。
- **测试**（先写）：协议值（`reads()` 不变、工具集）；写入范围；`finalize_blockers` 各情形（无源无渲染、有源未分析、源文件换了、`sections.json` 缺失/校验失败/通过）；`status_summary` 各情形；`prepare_turn` 两种形态；导入形态下 `render_music` 工具报错；既有 `test_music_stage.py` 的全部断言不改动通过（仅按协议值新增的工具名更新工具集断言）；提示词测试覆盖新增章节的关键词。
- **完成标准**：AC5 满足。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_music_stage.py tests/stages/test_music_import_stage.py tests/stages/test_music_prompt.py tests/stages/test_music_tool.py -q`；`make check`

### T7：`beatsheet` 的 MV 分支（完成）

- **目标**：节拍脚本能为 MV 校验和定稿。
- **涉及文件**：`backend/src/studio/stages/beatsheet/validate_beatsheet.py`、`backend/src/studio/stages/beatsheet/__init__.py`、`backend/src/studio/stages/beatsheet/prompt.md`、`backend/tests/stages/test_beatsheet_validate.py`、`backend/tests/stages/test_beatsheet_stage.py`
- **接口与要点**：
  - 分流：`upstream/music/sections.json` 存在即 MV（短片里 `music` 排在 `beatsheet` 之后，`upstream_of` 不会把它放进上游，不会误判）。
  - MV 的 `beatsheet.json`：顶层没有 `bpm`；每段 `{ref, intent, energy, moments[{at, visual_action}], id?, label?}`。`ref` 必填，`id`/`label` 可省，缺省取 `sections.json` 里同 `ref` 的值，给了 `id` 则必须等于 `ref`。
  - `check_beatsheet_mv(doc, sections_doc, analysis_doc) -> BeatsheetCheck`：出现 `bpm` 或 `bars` 报错；每个 `ref` 须存在于 `sections.json`，顺序一致，且**每个 `sections.json` 段落恰好被引用一次**（遗漏报错，见决策记录）；`at` 用 `parse_at(at, effective_bpm)`，须落在本段（段长取自 `sections.json`）内、按时间顺序；`energy` 取值、`visual_action` 非空沿用短片规则；总时长与目标时长的偏差检查沿用阈值，时长取 `range` 内总长。
  - `check_workspace(workdir)` 按分流调用；`finalize_blockers`、`status_summary`（MV：`N 个段落，BPM {bpm}，总时长 {s} 秒`）同步。工具描述补一句 MV 写法。
  - `reads()` 已含 `music`，不改。`prompt.md` 增加"音乐 MV"一节：段落边界和时长以音乐为准，只写意图、能量档位和时刻；`ref` 的写法；不写 `bpm`/`bars`；读 `upstream/music/sections.json` 与 `analysis.json` 的能量曲线来决定每段的 `energy`。
- **测试**（先写）：AC6 各条；`id` 与 `ref` 不一致；`at` 在 `bpm` 被 `sections.json` 覆盖后的换算；短片全部既有用例不变；两种形态的 `status_summary`。
- **完成标准**：AC6 满足。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_beatsheet_validate.py tests/stages/test_beatsheet_stage.py -q`；`make check`

### T8：`animation_html` 认得 MV（完成）

- **目标**：画面阶段在 MV 工作区读到完整的 MV 时间轴，运行时在没有命名事件时不出错。
- **涉及文件**：`backend/src/studio/stages/animation_html/prepare.py`、`backend/src/studio/stages/animation_html/prompt.md`、`backend/src/studio/stages/animation_html/common.py`（如预览/校验里读时间轴的地方）、`backend/src/studio/engines/render/html/`（运行时 `env.hit/span` 的实现，先读代码确认位置）、`backend/tests/stages/test_animation_html_stage.py`、`backend/tests/stages/test_animation_html_prompt.py`、`backend/tests/engines/test_html_*.py`（相关用例）
- **接口与要点**：
  - `_prepare_music_project`：`upstream/music/sections.json` 存在 → `TimelineSources(workdir, narration=False, music_source="import", prefix="upstream/")`；否则不变。失败照旧写 `timeline.error.txt`。
  - 运行时：`music.events` 为空时 `env.hit(name)` 返回 0、`env.span(name)` 返回 0 且不抛异常；`env.energy()` 取 `music.energy`；`env.bt/bar/moment` 照常。若现有实现已满足，只补测试。
  - 预览与校验里按"短片 vs 讲解"判断来源的地方（读 `common.py` 与 `render_preview_html.py`、`validate_scenes_html.py` 确认）同步认得 MV；不改写入范围与工具名。
  - `prompt.md`：新增"音乐 MV"一节：画面对齐网格和 `env.energy`，没有命名事件，不要依赖 `hit/span`；一个 `sections.json` 段落对应一个场景文件，场景 id 取段落 id；时间轴以截取区间起点为 0。
- **测试**（先写）：MV 夹具工作区的 `prepare_turn`（成功、缺 `sections.json`、`ref` 对不上）；运行时空事件的行为；提示词含新增章节；既有短片、讲解用例不变。
- **完成标准**：AC7 满足。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_animation_html_stage.py tests/stages/test_animation_html_prompt.py tests/engines -q -k "html or animation"`；`make check`

### T9：端到端阶段层测试与文档收尾（完成）

- **目标**：用 fake 运行时验证四阶段的联动，补文档，归档计划前的准备。
- **涉及文件**：新建 `backend/tests/stages/test_music_video_pipeline.py`、`docs/quality/QUALITY.md`、`docs/ARCHITECTURE.md`（若模块地图列了 `engines.audio` 的文件）、`docs/glossary.md`（`sections.json`、拟合网格、`range`）、`docs/plans/TODO.md`、本计划
- **接口与要点**：
  - 流水线测试：`build_pipeline(ProjectKind("html", False, "import"))` 得 `[concept, music, beatsheet, animation_html]`；`upstream_of` 各阶段的上游正确（`music`→`[concept]`，`beatsheet`→`[concept, music]`，`animation_html`→`[music, beatsheet]` 与 `reads()` 的交集）；用 T1 的夹具音频与 T5 的工具产出真实的 `analysis.*`，手写 `sections.json`，对着它构造 `beatsheet.json`，再让 `animation_html.prepare_turn` 读出时间轴；`music` 重新分析并定稿后，`beatsheet` 与 `animation_html` 按现有 stale 机制被标记。
  - `QUALITY.md`：登记已知缺口（librosa 在流行歌曲上的准确率未实测、变速曲不支持、恒定网格的漂移偏差、agent 听不到），与设计 §11 一致。
  - `TODO.md`：把"子项目 4"一行改为"4A 完成，4B 待做"，新增 4B 条目指向设计 §7、§8。
- **完成标准**：AC8 满足；`make check` 全绿。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_music_video_pipeline.py -q`；`make check`

## Review Focus

以下是设计隐含但没有任务专门测试的、最可能咬到真实用户的输入，每条都已落到对应任务的测试里：

1. **静音、极短（< 5 秒）、超长（> 10 分钟）、损坏、零字节的音频文件**：应给出明确中文错误，不写 `analysis.*`，不拖垮进程（T1、T3、T5）。
2. **散拍、变速、鼓点很弱的音频**：不崩溃，置信度低并给出手动修正的提示，而不是编出一个自信的错误网格（T2）。
3. **`sections.json` 的边界与浮点**：起点差几十毫秒、`range` 起点不是强拍、段落有 1 毫秒的缝隙或重叠、`range` 之外还有段落（T5）。
4. **换了源文件之后留下旧的 `analysis.json`/`sections.json`**：必须阻止定稿并提示重新分析，而不是用旧段落去切新歌（T6）。
5. **节拍脚本漏写或错序某个段落、或沿用短片写法（`bpm`/`bars`）**：应逐条报错并指出段落 id，而不是在时间轴构建时才崩（T4、T7）。

## 进度

- T1 完成：eb1982d（librosa 依赖、歌曲解码与恒定网格拟合）
- T2 完成：b5aa7c9（强拍相位、候选段落、能量曲线、置信度）
- T3 完成：f9383b2（分析图与 `song_job` 隔离运行）
- T4 完成：de875ac（时间轴的 MV 来源）
- T5 完成：919b259、741c2e1（`analyze_music` 与 `validate_sections`；压缩分析图先于写入）
- T6 完成：fad9c99、e303f90（`music` 阶段导入分支与提示词）
- T7 完成：dc6c58b、cc1cde8（`beatsheet` 的 MV 分支）
- T8 完成：16c41aa（`animation_html` 认得 MV）
- T9 完成：e142072（四阶段端到端测试、质量缺口、技术债、术语与架构文档）
- 整分支评审的修复：2df796b、463d100（MV 判定与音乐阶段共用同一个源文件信号；段落至少一小节；歌曲哈希分块读取；文档措辞）

## 下一步

- 4A 已完成。下一步是 4B（上传端点、音乐画布的导入形态、预览播放、worker 截取与混音），依据设计 §7、§8，需要先写计划。
- 4B 计划要带上：上传前清理旧的 `music/source.*`；`music` 定稿时拦截多个源文件；`timeline/load.py` 的 `_source_file`（`source.*` glob）与 `stages.common.music_source` 的取源规则对齐；`html_preview`/`api/music.py`/worker 对 import 形态的泛化。

## 决策记录

- 2026-10-05 — 导入形态的识别靠工作区里有 `music/source.<ext>`，`tools()` 取超集，工具在错误形态下返回明确提示 — 阶段协议拿不到项目设置（`system_prompt()`/`tools()` 无参），沿用设计 §6.1 与 3A `infer_sources` 的做法；不改 `StageDefinition` 协议，避免影响已批准的 agent 层接口。
- 2026-10-05 — 解码统一走 ffmpeg 转 22050 Hz 单声道再交给 librosa — 仓库已依赖 ffmpeg，避免 librosa 的 `audioread`/`soundfile` 对 m4a、mp3 的平台差异。
- 2026-10-05 — `MAX_SONG_SECONDS = 600`、最短 5 秒 — 设计只提到约 4 分钟的歌；上限留出余量，合成形态的 240 秒上限不动。
- 2026-10-05 — `analysis.json` 的 `offset` 定义为第一个强拍的时刻，MV 网格从 `range` 起点之后的第一个强拍起算 — 与现有 `_grid` 从 `offset` 起生成拍点、`downbeats = beats[::4]` 的实现一致；起点之前的前奏拍点不进网格，段落必须起于强拍所以不受影响。
- 2026-10-05 — `sections.json` 要求段落首尾相接并覆盖整个 `range`，`beatsheet` 的段落与它一一对应 — 设计只写"不重叠、对齐强拍"与"ref 存在且顺序一致"；这里收紧，因为每一秒都要属于某个场景，否则画面阶段会出现无场景的空白帧。想裁掉前奏或尾声，只要不写那几段（缺省的有效区间取段落跨度），显式 `range` 必须与段落跨度一致，主要供 4B 的画布展示与成片截取使用。属于对设计的细化，若负责人不同意可放宽为警告。
- 2026-10-05 — MV 的 `hash` = `sha256(timeline_hash + source_hash + range)` — 设计 §5 要求哈希覆盖 `source_hash`，而时间轴 schema 不改字段（设计 §5），所以在加载层合成。

- 2026-10-05 — 歌曲 BPM 边界取 `timeline.build.BPM_RANGE`（40–240），折叠优先区间 60–200 — 计划原写 60–200，那是短片节拍脚本的范围，写错了。
- 2026-10-05 — 歌曲分析不设内存上限 — 设计 §2 写了"内存上限"，但 runner 只有 CPU 与文件大小限制，macOS 的 `RLIMIT_AS` 不可靠；内存由 `MAX_SONG_SECONDS` 的输入上限兜底（约 106 MB），登记为 TD-71。属于对已批准设计的偏离，已向负责人说明。
- 2026-10-05 — MV 的节拍脚本不套用短片的 8–180 秒总长与 12 段上限 — 歌曲可达数分钟，设计 §6.2 只要求 `ref` 合法与 `at` 在本段内。
- 2026-10-05 — 节拍脚本校验遇到 `sections.json` 的 `range` 与段落跨度不一致时直接报错，不在校验器里裁剪 — 与 `music` 阶段的规则一致，时间轴构建仍宽松裁剪作为兜底。
- 2026-10-05 — 没有命名事件时 `env.span` 返回 `[]`，不是 `0` — 沿用运行时既有契约，`0` 会让 `.forEach`/`.length` 出错。
- 2026-10-05 — `animation_html` 判断 MV 要求上游同时有 `sections.json` 与白名单内的源文件（`stages.common.music_source`，与 `music` 阶段共用）— 整分支评审发现只看 `sections.json` 时，合成项目里残留一个该文件会被误判成 MV。
- 2026-10-05 — `sections.json` 的每个段落至少跨一小节（起止吸附到不同强拍）— 整分支评审发现两端各贴一个强拍的几十毫秒"段落"能通过校验。

## 意外与发现

- 首次 `librosa` 的 `beat_track` 在新环境里约 27 秒（numba 即时编译），之后的新进程约 2 秒；`beat_track` 返回的速度被量化（120 BPM 会变成约 117.45），所以网格从拍点时刻拟合。记录在 [librosa.md](../../references/librosa.md)。
- 强拍相位的检测窗口要取拍点前 3 帧到后 1 帧，窗口只取 ±1 帧时合成节拍音频会选错相位。

## 阻塞

- 无

## 验证记录

- 2026-10-05，分支末端 `463d100`：`make check` 全绿（后端、前端 1056 个用例、import-linter、文档检查）。
- AC1–AC3：`tests/engines/test_audio_song.py`、`tests/stages/test_music_import_tools.py`、`tests/stages/test_validate_sections.py`；每个任务经独立评审，评审指出的"永远不会失败"的断言均已改成有区分力的断言，并做过变异检查。
- AC4：`tests/timeline/test_import_timeline.py`、`tests/timeline/test_load.py`。
- AC5、AC6、AC7：`tests/stages/test_music_import_stage.py`、`test_beatsheet_validate.py`、`test_animation_html_stage.py`（含"合成项目带残留 `sections.json`"的分流用例）。
- AC8：`tests/stages/test_music_video_pipeline.py`，用真实 `analyze_music` 与真实 `stage_flow`，含"歌曲更换后下游 stale"与"music 不变则不 stale"的对照。
- 没有真实模型冒烟，也没有真实歌曲实测（设计 §2、§11：已确认跳过，记入 QUALITY.md 的已知缺口）。
