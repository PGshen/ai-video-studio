# 「配乐与动画」合并阶段（`produce`）

状态：待批准（2026-10-06）。本文是对 [合成配乐短片设计](2026-10-05-synth-music-reel.md)（以下简称"子项目 3 设计"）和 [导入音乐与 MV 设计](2026-10-05-import-music-mv.md)（以下简称"子项目 4 设计"）的**取代性补充**：只取代两者中与 `beatsheet` 阶段、网格、节拍脚本、`sections.json`、阶段拆分有关的部分，范围见 §10。已批准的旧文档不修改。

## 1. 背景与目标

「动态图形短片」和「音乐 MV」按 `concept → beatsheet → music → animation_html`（MV 为 `concept → music → beatsheet → animation_html`）四步走。实际使用下来效果不好：

- 节拍、配乐、画面往往是联动的，拆开后每一步都锁死上游：节拍脚本在没有音乐时就把时刻定死，配乐只能照着做，画面只能照着配乐的事件做，没有回头调整的权限。
- 现在的模型有能力自己决定结构、对齐方式和取舍，预先规定网格与时刻反而是约束。

**目标**：两个阶段——「创意与要求」（人确认）→「配乐与动画」（模型基于前者自己迭代，配乐与画面放在一起做）。两种无旁白形态（短片、MV）都改。讲解类不动。

**不做**：旧项目数据兼容（调试期无数据包袱，旧项目直接作废）；讲解类形态的任何改动；`timeline` schema 的字段变更。

## 2. 已确认的决定

| 项 | 决定 |
|---|---|
| 范围 | 动态图形短片、音乐 MV 都改；讲解类（Manim / HTML，含合成与导入配乐）不动 |
| 控制权 | 网格、段落、关键时刻、镜头划分、如何与音乐对齐，全部由模型决定；系统只提供客观事实与最小校验 |
| 事实层 | 保留客观事实（时长、事件、能量），删除创作性约定（`grid`、`moments`、节拍脚本、MV 的 `sections.json`） |
| 阶段 | 新阶段键 `produce`，界面名「配乐与动画」 |
| 镜头划分 | 模型自己写 `animation/shots.json`，系统只检查首尾相接、覆盖整段、`id` 合法 |
| MV 的歌曲 | 上传与分析提前到 `concept` 阶段 |
| 旧项目 | 不兼容 |

## 3. 流水线

| 形态 | 旧 | 新 |
|---|---|---|
| 动态图形短片 `motion_reel` | `concept → beatsheet → music → animation_html` | `concept → produce` |
| 音乐 MV `music_video` | `concept → music → beatsheet → animation_html` | `concept → produce` |
| 讲解类（四种） | 不变 | 不变 |

- 删除 `beatsheet` 阶段（`stages/beatsheet/`、`validate_beatsheet`、注册与 `STAGE_TITLES`），及时间轴里的 `layers_from_beatsheet` 路径。
- `produce` 加入注册表与 `STAGE_TITLES`（「配乐与动画」）；前端 `STAGE_TITLES` 同步。
- `music`、`animation_html` 保留给讲解类，其工具函数由 `produce` 复用，不复制。
- `build_pipeline`、预设描述（`motion_reel`："先定概念与节拍"、`music_video`）同步改文案。

## 4. 「创意与要求」（`concept`）

- `brief.md` 新增固定章节 **「硬性要求」**：用户确认过的必须项与禁忌（风格、必须出现的元素、时长上下限等）。其余章节不变。
- `check_concept` 只多检查该章节存在，不评价内容。
- `concept` 是流水线里**唯一的人工确认点**；定稿后 `produce` 不再需要人工放行中间产物。
- **MV**：`concept` 增加歌曲上传入口与 `analyze_music` 工具（复用 `stages.music.analyze`、上传端点与分析的子进程隔离），agent 基于真实的歌写创意与要求。上传端点的写入位置（`music/source.<ext>`）不变，只是画布入口从音乐画布移到概念阶段。`concept` 的 `artifact_dirs` 因此增加 `music`，工具托管文件加上 `music/source.*`、`music/analysis.json`、`music/analysis.png`。
- 短片的 `concept` 无上传与分析。`analyze_music` 在无源文件时返回明确提示，与现有"在错误形态下返回提示"的做法一致。

## 5. `produce` 阶段

### 5.1 定义

| 项 | 内容 |
|---|---|
| `name` / `allow_web` / `reads()` | `produce` / 否 / `[concept]` |
| 可写范围 | `music/compose.py`（短片）、`music/range.json`（MV）、`animation/shots.json`、`animation/scenes/*.js`、`animation/lib/*.js`、`animation/global.js`、`animation/assets/*` |
| 工具托管文件 | `music/music.wav`、`music/events.json`、`music/analysis.json`、`music/analysis.png`、`music/render.json`、`music/source.*` |
| 工具 | 短片：`render_music`；MV：`analyze_music`；共用：`validate_scenes_html`、`render_preview_html`、`suggest_upstream_change` |
| `artifact_dirs()` | `["music", "animation"]` |
| 形态判断 | 与现有 `music` 阶段一样按工作区内容分流：有 `music/source.<ext>` 为 MV，否则为短片；`tools()` 取超集，错误形态下返回明确提示 |

### 5.2 工作方式

系统不规定顺序。提示词只给目标与可用手段：读 `brief.md`，决定 BPM、结构与镜头，写配乐，渲染并读分析，写镜头，校验、预览，必要时回头改配乐或镜头划分，直到满意。模型对配乐与画面的任何一边改动后，需要自己判断是否重渲、是否调整另一边。

### 5.3 产物

| 文件 | 谁写 | 说明 |
|---|---|---|
| `music/compose.py` | agent（短片） | 合成脚本；**不再收到时间轴作为输入**。环境变量只有 `STUDIO_OUT_WAV`、`STUDIO_OUT_EVENTS`（`STUDIO_TIMELINE` 取消） |
| `music/music.wav`、`events.json`、`analysis.json`、`analysis.png`、`render.json` | `render_music` | `events.json`：`{ "duration", "bpm"?, "events": [{ name, kind, start, end }] }`，`bpm` 可选；`render.json`：`{ script_hash, wav_hash, duration, rendered_at }`（去掉 `base_hash`） |
| `music/source.*`、`analysis.json`、`analysis.png` | api 上传 / `analyze_music`（MV） | 与子项目 4 一致，去掉对 `sections.json` 的依赖 |
| `music/range.json` | agent（MV） | `{ "start", "end" }`，全局秒，相对源文件；**只需 `0 ≤ start < end ≤ 音频时长`**，不要求落在强拍上；缺省时用整首歌 |
| `animation/shots.json` | agent | `{ "shots": [{ "id", "label", "start", "end" }] }`，秒，相对成片时间轴 |
| `animation/scenes/<id>.js` | agent | 与子项目 2 的镜头协议一致：`{ draw(ctx, lt, env), pad? }` |

`shots.json` 的校验（`validate_shots`，由 `validate_scenes_html` 先行调用，也可在 `finalize_blockers` 重跑）：

| 检查 | 级别 |
|---|---|
| JSON 合法、字段齐全 | 错误 |
| `id` 合法（沿用 `_ID_PATTERN`）且唯一；镜头数 ≥ 1 | 错误 |
| 首尾相接：第一个 `start = 0`，相邻镜头 `end = start`，最后一个 `end` 等于 `duration`（容差 1ms） | 错误 |
| 每个 `id` 都有对应的 `animation/scenes/<id>.js` | `validate_scenes_html` 报错；定稿时阻止 |
| 镜头数超过 40 | 警告 |

### 5.4 定稿条件（`finalize_blockers`）

- 短片：`render.json` 存在；`compose.py` 哈希与记录一致；`music.wav` 存在且哈希一致。**不再比对时间轴 `base_hash`**。
- MV：`analysis.json` 对应当前 `source.*`；`range.json`（若存在）合法。
- 共用：`shots.json` 合法；每个镜头都有对应文件。
- `validate_scenes_html` 不作为定稿阻止条件（沿用现有行为）；预览与校验是模型自检手段。

### 5.5 `status_summary`

短片："已渲染 X 秒，N 个事件；M 个镜头"；MV："已分析，X 秒，BPM B；M 个镜头"；缺项时点明缺哪一项。

## 6. 事实层（`studio.timeline`）

`Timeline` schema **字段不变**（讲解类仍用 `grid`）；短片与 MV 的读取路径改为：

| 层 | 短片 / MV 的来源 |
|---|---|
| `duration` | 短片：`events.json` 声明的时长，且与 `music.wav` 实际时长相差 ≤ 50ms，否则报错；MV：`range` 的长度（缺省为整首歌） |
| `sections` | `animation/shots.json`（改称"镜头"仅在文档层面；字段仍叫 `sections`，运行时沿用） |
| `music.events` | 短片：`events.json`；MV：来自分析结果（鼓点、强拍等客观事件）；起点相对成片时间轴（MV 已减去 `range.start`） |
| `music.energy` | 对音频计算（`analysis.json` 的 `energy` / `hop`） |
| `grid`、`moments` | **空**（`None` / `[]`）；`env.bt/bar/moment` 因而不可用，调用时抛出清晰错误并提示使用 `hit/span/energy` |

- 新增读取入口：`TimelineSources` 增加形态 `produce`，不再依赖 `beatsheet.json`、`sections.json`；删除 `imported.py` 中的节拍脚本、强拍对齐、`moments` 和段落边界校验。`analyze_music` 的 BPM、拍点等分析结果仍写进 `analysis.json`，只作为模型的**可选参考**，不进入时间轴。
- `timeline_hash` 仍覆盖整份时间轴；`render.json` 与 worker 的缓存键均从这里派生，不新增哈希口径。
- 时间轴读取在 `produce` 内**由各工具即时构建**，不再依赖每轮 `prepare_turn` 写 `upstream/timeline.json`（同一阶段内的文件改了就要立刻反映）。`prepare_turn` 只负责复制金样本。

## 7. 校验与预览

沿用子项目 2、3 的校验框架，只改下面几处：

- **音乐敏感度检查**（整体平移 0.2 秒）：从错误**降为警告**，点名哪些镜头对平移不敏感。理由：模型可以有意让某个镜头不跟随音乐。平移的对象为 `music.events` 与 `energy`（`grid`、`moments` 已不存在）。
- **字面量时间静态警告**：保留。
- **`render_preview_html` 采样**：必选点改为——镜头起止附近、能量峰值、出现次数最少的几类事件的起点；再用均匀采样补到 16 张；其余（边界帧差、`pad` 重叠、图的形式）不变。
- 工具返回体积：所有返回给模型的文本与图像要有大小上限，事件与能量只返回摘要并提示按需读取文件（与 `JSON message exceeded maximum buffer size` 的缺陷合并处理，见 §11）。

## 8. 成片（worker）

- `worker_html` 的前置检查：短片检查 `music.wav`、`events.json`、`analysis.json`、`render.json` 齐全，且 `wav_hash` 与记录一致；**去掉对 `base_hash` 的比对**。MV 检查源文件与分析一致。
- 缺 `shots.json` 或镜头文件缺失时，错误信息点名文件。
- 混音、`range` 截取、缓存键口径不变。

## 9. 前端

- `produce` 的画布合并：以现有动画预览（带配乐同步播放）为主，增加配乐的「脚本 / 事件 / 分析」标签页（复用 `MusicCanvas` 的组件）。
- MV 的上传区移到 `concept` 的画布。
- 阶段导航、阶段标题、创建项目对话框的流水线描述随 `STAGE_TITLES` 与预设更新。
- 具体布局与组件拆分在计划里读完 `MusicCanvas` 与动画画布后再定；设计层面只约束上述归属。

## 10. 被取代的内容

| 旧文档 | 被取代 |
|---|---|
| 子项目 3 设计 | §6.2（`beatsheet` 阶段）、§5 中 `grid` / `moments` 与 `beatsheet` 来源、§7 中"时刻必须由时间轴推出"与 `STUDIO_TIMELINE`、`base_hash` 与 `finalize_blockers` 中的时间轴比对、§6.3 中依赖 `moment` 的提示词与校验、阶段拆分 |
| 子项目 4 设计 | §3–§4 中 `sections.json` 与 `validate_sections`、强拍对齐要求、`range` 的强拍约束、`music` → `beatsheet` 的流水线顺序、MV 版 `beatsheet` |
| 总设计 | §7.2（节拍脚本）对两种无旁白形态不再适用 |

不变：`Timeline` schema、`env` 的 `hit/span/energy`、`engines.audio`、`engines.render.html`、镜头协议、讲解类全部阶段。

## 11. 已知问题与风险

| 风险 | 处理 |
|---|---|
| 去掉机械对齐后，模型可能做出与音乐不同步的画面 | 保留音乐敏感度警告与预览的事件采样；提示词要求模型用预览自查；这是有意的取舍 |
| `produce` 单阶段上下文更重 | 工具返回体积设上限（§7）；金样本与技法参考按需读文件，不整段塞进提示词 |
| 现有缺陷：配乐阶段单条消息超过 1MB（`JSON message exceeded maximum buffer size of 1048576 bytes`） | 先定位是哪个工具返回或哪份产物过大，**在合并之前单独修复**；合并设计依赖该修复，但不以本文为依据决定修法 |
| 人工检查点减少 | `concept` 定稿前的"硬性要求"是唯一契约；`produce` 内用户仍可随时对话与回滚快照 |
| 旧项目不兼容 | 已确认接受；旧项目的 `pipeline` 设置含已删除的阶段，创建新项目即可 |

## 12. 测试

- **时间轴**：`produce` 读取（短片、MV）的成功与各类失败（`shots.json` 缺失 / 不连续 / 不覆盖、`events.json` 时长与音频不符、`range` 越界）；`env.bt/bar/moment` 调用的明确报错；`timeline_hash` 对 `shots.json` 与 `range` 敏感。
- **阶段层**：`produce` 阶段的注册、写入范围、`finalize_blockers`、`status_summary`；`concept` 的 MV 上传分析与 `check_concept` 新增章节；用 fake 运行时跑通短片与 MV 两条完整流水线并能定稿。
- **工具**：`render_music` 无 `STUDIO_TIMELINE` 的运行与失败路径不改动旧产物；`validate_shots`；`validate_scenes_html` 的警告降级；预览采样；工具返回体积上限。
- **worker**：前置检查去掉 `base_hash` 后的齐全 / 不一致 / 缺失路径；MV 的 `range` 截取。
- **结构**：import-linter 契约不变；删除 `beatsheet` 后无残留引用。
- **前端**：vitest 覆盖阶段标题、`produce` 画布的标签与播放来源、MV 上传区在 `concept`；L4 由控制者在浏览器中验证两种形态。
- 真实模型冒烟：短片、MV 各一次，走完 `concept → produce` 并出成片。

## 13. 实施

一份设计，一份计划，放在 `docs/plans/active/`：

1. 时间轴读取与 `shots.json` 校验（先写失败测试）。
2. `render_music` 去时间轴输入；`produce` 阶段与工具、定稿条件。
3. `concept` 的硬性要求与 MV 的上传分析入口。
4. 校验降级、预览采样、工具返回体积上限。
5. worker 前置检查。
6. 删除 `beatsheet` 与旧路径；流水线、预设、`STAGE_TITLES` 与文档（ARCHITECTURE、QUALITY、TODO）。
7. 前端合并画布与上传区迁移。
8. 冒烟与 L4。

**记入 `docs/plans/TODO.md`**：1MB 缓冲区缺陷（先于本计划修复）；讲解类是否也取消阶段拆分，待本形态验证后再评估。
