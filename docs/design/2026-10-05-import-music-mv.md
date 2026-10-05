# 子项目 4：导入音乐与音乐 MV

状态：待批准（2026-10-05）。本文是 [多形态视频流水线设计](2026-10-04-html-video-pipeline.md)（以下简称"总设计"）§11 中子项目 4 的实现级设计，不修改总设计，也不修改已批准的 [子项目 2 设计](2026-10-04-timeline-html-engine.md) 与 [子项目 3 设计](2026-10-05-synth-music-reel.md)；对它们的补充集中列在 §10。

## 1. 目标与范围

**交付**：第四种形态「音乐 MV」（`engine=html`、`narration=false`、`music_source=import`）能走完整条流水线并出成片。

流水线：`concept → music → beatsheet → animation_html`。用户上传一首歌；系统用 librosa 分析出网格、候选段落与能量曲线；agent 修正出 `sections.json`（含可选截取区间 `range`）；再按段落写节拍脚本与画面；worker 输出音轨取自截取后原曲的 MP4。

**非目标**：歌词、变速曲、AI 音乐服务（以后与导入共用分析路径）、`concept` 的专用画布（沿用通用文件画布）、项目级分辨率与 fps、librosa 准确率的前置实测（见 §2）。

**一份设计，两份计划**（沿用 2A/2B、3A/3B 的切法）：

| 计划 | 内容 | 验收 |
|---|---|---|
| 4A | `engines.audio` 的分析（librosa）；`music` 阶段的导入分支（`analyze_music`、`validate_sections`、提示词、定稿条件）；`studio.timeline` 的 MV 读取；MV 版 `beatsheet` 的校验与提示词；阶段层测试 | agent 能在界面里走完 `concept → music → beatsheet → animation_html`（音频先以夹具文件放进工作区） |
| 4B | 上传端点；音乐画布的上传区与段落展示；预览播放导入音频；worker 的截取与混音；成片冒烟 | 用户上传一首歌，整条流水线出带原曲音轨的 MV |

## 2. 已确认的决定

| 项 | 决定 | 依据 |
|---|---|---|
| librosa 准确率实测 | 跳过；记为已知缺口，靠 `sections.json` 手动修正兜底 | 2026-10-05 负责人确认（覆盖总设计 §12 的前置要求） |
| 网格模型 | 把检测拍点拟合成**恒定** `bpm` + `offset`；强拍相位取能量最强的一拍；agent 可在 `sections.json` 里覆盖 `bpm`/`offset` | 2026-10-05 负责人确认；复用子项目 3 的记法换算与 `hit/energy` 运行时 |
| 拆分 | 4A（agent 侧）加 4B（上传、画布、混音） | 沿用 2A/2B、3A/3B |
| 分析的运行位置 | `analyze_music` 是我们自己的代码，不进 agent 脚本沙箱；用子进程加超时与内存上限隔离，避免 librosa 卡住 api | 2026-10-05 设计讨论 |
| 总设计的未变部分 | 时间轴分层与 schema（不改字段）、`env` 契约、`reads()`/`upstream_of`、`animation_html` 的写入范围 | 总设计 §3–§5 |

## 3. 产物（`music/` 目录）

| 文件 | 谁写 | 说明 |
|---|---|---|
| `source.<ext>` | api 上传 | 格式白名单（mp3、wav、m4a、flac、ogg）；大小上限；只经上传端点写入（工具托管） |
| `analysis.json` | `analyze_music` | `source_hash`、`duration`、拟合的 `bpm`/`offset`、拟合残差、置信度、`beats`、`downbeats`、候选段落边界、`hop` 与 `energy` |
| `analysis.png` | `analyze_music` | 波形 + 能量 + 网格 + 候选边界，复用子项目 3 的绘图 |
| `sections.json` | agent | 见下 |

`sections.json`：

```
bpm?, offset?                        # 可选；覆盖分析拟合值
range?  { start, end }               # 可选；截取区间，必须落在强拍上
sections[{ id, label, start, end }]  # 全局秒（相对源文件）；起止必须落在强拍上
```

`music` 阶段的写入范围：可写 `music/sections.json`；`source.*`、`analysis.json`、`analysis.png` 由工具或 api 托管。

## 4. 工具

- **`analyze_music`**：对 `music/source.*` 做分析，重写 `analysis.json` 与 `analysis.png`。同一源文件结果可复现。返回：图、BPM、拟合残差、置信度、候选段落、总时长；低置信或残差大时明确提示"请手动修正 `sections.json`"，不阻止定稿。音频无法解码时返回明确错误，不写 `analysis.*`。
- **`validate_sections`**：段落不重叠、有序、起止对齐强拍、落在音频范围内；`range` 起止对齐强拍且包含全部段落；`id` 唯一。
- 有效 BPM 与总长的合理范围沿用 `timeline` 现有 `_bpm_error`。

## 5. 时间轴（`studio.timeline`）

位置不变，仍是纯能力层。schema 不改字段；`build_timeline` 增加 MV 来源，`TimelineSources(music_source="import")` 读取 `music/analysis.json` 与 `music/sections.json`。

| 层 | MV 的来源 |
|---|---|
| `grid` | `sections.json` 的 `bpm`/`offset`（有则优先），否则取 `analysis.json`；每拍一个时刻，每 4 拍一个强拍；以 `range` 起点为 0，覆盖截取后的全长 |
| `sections` | `sections.json` 的段落，裁到 `range` 内，时间以 `range` 起点为 0 |
| `narration` | 空 |
| `moments` | `beatsheet.json` 的 `moments`，`at` 用 `parse_at(at, bpm)` 换算成相对段落起点的秒，再加段落起点 |
| `music` | `file` 指向 `music/source.<ext>`；`energy` 取自 `analysis.json` 并按 `range` 截取；`events` 为空 |

时间轴哈希覆盖 `range`、网格与段落，也覆盖 `analysis.json` 的 `source_hash`。读取失败统一成 `TimelineError`（沿用现有汇总方式）。

## 6. 阶段

### 6.1 `music`（导入形态）

- 阶段按项目 `music_source` 分支；与合成形态共用阶段键 `music`，工具集和提示词按形态选择。由于阶段对象拿不到项目设置，沿用 `infer_sources` 的做法：工作区里有 `music/source.*` 即为导入形态。
- **提示词要点**：先调用 `analyze_music`；看图与候选边界；写 `sections.json`（起止对齐强拍，标签有意义，如 intro/verse/chorus）；`validate_sections` 通过后再请用户确认；自动分段常不准，修正写在 `sections.json`，不改派生数据。
- **`reads()`**：`[concept, narrative, beatsheet]` 与项目流水线取交集后，MV 里只剩 `concept`。
- **定稿条件**：`analysis.json` 的 `source_hash` 与当前源文件一致；`sections.json` 通过 `validate_sections`。源文件换了则 blocker：「源文件已更换，需要重新 `analyze_music`」。
- **状态摘要**：「已分析：BPM、时长、置信度；N 个段落」。

### 6.2 `beatsheet`（MV 部分）

- 总设计 §7.2 已定义：MV 中不允许出现 `bpm`；段落用 `ref` 指向 `music/sections.json` 的段落 id，而非 `bars`。
- **`validate_beatsheet`**：每个 `ref` 存在于上游 `sections.json` 且顺序一致；所有 `at` 落在本段范围内。
- 提示词补充 MV 段：段落边界和时长以音乐为准，agent 只写意图、能量档位和时刻。
- `reads()` 在 MV 中为 `[concept, music]`。

### 6.3 `concept`、`animation_html`

`concept` 不改。`animation_html` 的 `reads()` 与写入范围不变；`prepare_turn` 经 `TimelineSources(music_source="import")` 读取 MV 时间轴。`env.hit/energy/moment/span` 中，`energy` 取自导入分析的能量曲线；MV 没有命名事件，`hit/span` 无数据（返回空，不报错），提示词说明 MV 画面对齐网格与 `energy`。

## 7. 上传、画布与预览（4B）

- **上传端点**：`POST /api/projects/{id}/music/source`。校验：项目 `music_source=import`、扩展名白名单、大小上限、文件头嗅探确认是音频。写入固定路径 `music/source.<ext>`（工作区安全解析），旧的 `source.*` 先清理。换歌后 `analysis.*` 与 `sections.json` 保留但标为 stale，不自动删除，由用户让 agent 重新分析。
- **`music/meta` 与 `music/audio`**：现有端点泛化到导入形态；meta 增加 `source`（文件名、哈希、时长）、分析摘要、`sections.json` 校验结果、`stale`；audio 返回源文件，`Range` 沿用。
- **音乐画布（导入形态）**：未上传时为上传区；已上传后显示播放器 + 波形，叠加网格、强拍、段落色块与截取区间，点击跳转；右侧显示分析摘要和校验结果。
- **预览播放**：音频源按形态取（合成取 `music.wav`，导入取 `source.*`），按 `range` 起点偏移播放。
- **创建项目对话框**：音乐 MV 预设已存在，不改。

## 8. 成片（4B）

worker 的 `final_render`：HTML 引擎输出无声视频；音频步骤用 ffmpeg 按 `range` 截取源文件，淡入淡出，统一 AAC，`-movflags +faststart`。无旁白，因此无侧链压低。缓存键新增源文件哈希与 `range`；`output/final.json` 的 `audio_sources` 记录源哈希与 `range`。长歌（约 4 分钟）的出帧时长在冒烟中实测，结论写进 `docs/references/`。

## 9. 测试与错误处理

| 层 | 测什么 |
|---|---|
| 能力层 | 用 NumPy 生成已知 BPM（120/96/140）、已知 offset（约 80ms）的节拍音频：拟合 BPM 误差 < 0.5%、offset 误差 < 30ms；散拍与变速的合成音频置信度低；同一文件两次分析一致 |
| 时间轴 | `range` 截取后以起点为 0；覆盖 `bpm`/`offset` 优先；`at` 换算；`ref` 不存在、段落越界报错；哈希随 `range`、网格、`source_hash` 变化 |
| 阶段层 | `validate_sections` 各类错误；定稿条件（源文件更换即 blocked）；fake 运行时跑通四阶段，产物齐全且能定稿；上游 `music` 重新定稿后下游走 stale |
| api | 白名单、大小上限、固定路径、换歌标 stale、音频端点 `Range` |
| worker | 截取与混音：成片时长与音轨时长一致，哈希进 `final.json`，改 `range` 使缓存失效 |
| L4 浏览器 | 上传区、波形与段落叠加、点击跳转、预览播放 |
| 真实模型冒烟 | 一首短歌走完整条流水线（`make smoke`，默认不跑；用本地 Claude 登录） |

| 情况 | 处理 |
|---|---|
| 格式或大小不合规 | api 422，画布提示 |
| 音频无法解码 | `analyze_music` 返回明确错误 |
| 低置信、拟合残差大 | 提示手动修正，不阻止定稿 |
| 源文件在分析之后被换 | 定稿 blocker |
| `sections.json` 校验失败 | 定稿 blocker，逐条列出 |
| 上游时间轴变化而下游未跟上 | 现有 stale 机制 |

## 10. 对已批准设计的补充与修订

| 项 | 内容 |
|---|---|
| 总设计 §12 | "librosa 准确率实测"前置要求被跳过（负责人 2026-10-05），改为已知缺口，记入 `docs/quality/QUALITY.md` |
| 总设计 §4.3 | MV 的 `grid` 改为恒定 `bpm` + `offset`（拟合值，可被 `sections.json` 覆盖），不是逐拍的检测值 |
| 子项目 3 设计 | `music` 阶段由单一合成形态扩为"合成 / 导入"两个分支；`infer_sources` 增加按工作区内容识别导入形态 |
| 新依赖 | `librosa`（带 numba）；4A 计划里单独一个任务验证安装、首次导入耗时与 import-linter 契约 |

## 11. 已知缺口

| 缺口 | 说明 |
|---|---|
| librosa 在流行歌曲上的强拍与分段准确率未实测 | 靠置信度提示与 `sections.json` 手动修正兜底 |
| 变速曲、散拍 | 第一版不支持；拟合残差过大时提示 |
| 恒定网格对轻微漂移的歌有几十毫秒偏差 | 取舍见 §2；以后需要时可加"逐拍参考层" |
| agent 听不到声音 | 与子项目 3 相同，靠分析图加用户试听 |
