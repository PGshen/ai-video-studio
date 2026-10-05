# 子项目 3：合成配乐与动态图形短片

状态：已批准（2026-10-05）。本文是 [多形态视频流水线设计](2026-10-04-html-video-pipeline.md)（以下简称"总设计"）§11 中子项目 3 的实现级设计，不修改总设计，也不修改已批准的 [子项目 2 设计](2026-10-04-timeline-html-engine.md)；对它们的补充和修订集中列在 §12。

## 1. 目标与范围

**交付**：两种形态能走完整条流水线并出成片。

| 形态 | 流水线 | 成片音轨 |
|---|---|---|
| 动态图形短片（`motion_reel`） | `concept → beatsheet → music → animation_html` | 只有合成配乐 |
| 知识讲解 + 合成背景乐（`explainer_html`，`music_source=synth`） | `topic → narrative → music → animation_html` | 旁白，加被旁白压低的背景乐 |

agent 写节拍脚本、写 NumPy 合成脚本并用图和指标自检，再按节拍写画面；前端能播放配乐、编辑脚本、实时预览；worker 输出带配乐的 MP4。Manim 路径、无配乐的讲解和老项目不受影响。

**非目标**：导入音乐（`music_source=import`）、`analyze_music`、librosa、音乐 MV（子项目 4）；歌词；变速曲；AI 音乐服务；`concept` 与 `beatsheet` 的专用画布（用通用文件画布）；项目级分辨率与 fps。

**一份设计，两份计划**（沿用 2A/2B 的切法）：

| 计划 | 内容 | 验收 |
|---|---|---|
| 3A | `studio.timeline` 补网格、时刻、配乐三层与按形态读取；`engines.audio`；`concept`、`beatsheet`、`music` 三个阶段及其工具、提示词、`prepare_turn`；HTML 运行时的 `hit/energy/moment/span`；`animation_html` 的校验与预览泛化；注册与契约；阶段层测试；真实模型冒烟（短片，到画面为止） | agent 能在界面里走完 `concept → beatsheet → music → animation_html`，两种形态可创建 |
| 3B | 背景乐混音（侧链）与 worker 改动；音乐的 api 端点；音乐画布与预览播放改造；成片冒烟 | 两种形态能出带音轨的成片，前端可试听、可改脚本、可预览 |

## 2. 已确认的决定

| 项 | 决定 | 依据 |
|---|---|---|
| 范围 | 同时做短片与"讲解 + 合成背景乐" | 2026-10-05 负责人确认 |
| 拆分 | 3A（agent 侧）加 3B（混音、api、前端） | 沿用 2A/2B；负责人未异议 |
| 脚本沙箱 | 复用 macOS Seatbelt 沙箱，网络禁用，超时 120 秒；沙箱不可用时失败关闭 | 沿用 ADR 0009 |
| 画图 | NumPy 加 Pillow 自绘，不引入 matplotlib | 不增加依赖 |
| 无旁白的讲解背景乐 | 没有节拍脚本；agent 自选 BPM 并写进 `events.json`，网格取自这个声明值，段落仍是配音镜头 | 同上 |
| 能量曲线 | 系统从 WAV 计算，agent 不手写 | 同上；避免能量与声音不一致 |
| `concept`、`beatsheet` | 不写代码；用通用文件画布 | 同上；专用画布延后 |
| 总设计的未变部分 | 时间轴分层、`env` 契约、阶段定义、`animation_html` 的写入范围与工具名、`reads()` 与 `upstream_of` | 总设计 §4–§7 |

## 3. 小试结论对设计的约束

[motion-reel-spike](../references/motion-reel-spike.md)（2026-10-05）：两个运行写出了踩节拍的画面，两个运行写出了对齐网格的配乐，谱图加指标足以迭代结构、节奏和强弱，音色听不到。它暴露的问题在本设计逐条处理：

| 问题 | 处理 |
|---|---|
| 平移敏感度对短片没有区分力（HUD 读节拍，每帧都变） | 敏感度检查逐镜头单独做，不含 `global.js`（§6.3）；另加字面量时刻的静态警告 |
| `env.hit` 只适用瞬发事件，扫频取不到起止 | 增加 `env.span(name)`（§5） |
| 对齐率不是音乐性指标；检测盲区拉低匹配率 | 指标分为"对齐类"与"需要用户听"；声明但检测不到的事件单独列出，不计入匹配率（§7.3） |
| 配乐脚本是否写死秒数 | `render_music` 自动用另一套 BPM 或总长重跑一遍（§7.4）；两个 agent 小试里已自发这么做 |
| 耗时与费用是上次小试的数倍 | 提示词要求按镜头逐个"写 → 校验 → 预览 → 修"；配乐脚本分段落写；不加系统层限制 |
| 画面与音乐没有联调 | 3A 的阶段层测试用 `render_music` 的真实产物构建时间轴，再喂给画面阶段（§10） |

## 4. 时间轴扩展（`studio.timeline`）

位置不变，仍是纯能力层（标准库加 pydantic，import-linter 契约不变）。schema 子项目 2 已写全，**不改字段**；本阶段让 `build_timeline` 支持 `grid`、`moments`、`music`。

### 4.1 三种来源

| 形态 | `sections` | `grid` | `narration` | `moments` | `music` |
|---|---|---|---|---|---|
| 短片 | `beatsheet.json` 的段落，时长 = `bars × 4 × 60 / bpm`，首尾相接 | `bpm` 与 `offset=0`，每拍一个时刻，每 4 拍一个强拍，覆盖整片再多一拍 | 空 | `beatsheet.json` 的 `moments`，`at` 用 `parse_at(at, bpm)` 换成相对段落起点的秒再加段落起点 | 有 |
| 讲解 + 背景乐 | 叙事镜头（同子项目 2） | `events.json` 声明的 `bpm`，`offset` 取声明值（缺省 0），覆盖整片 | 叙事（同子项目 2） | 空 | 有 |
| 讲解，无配乐 | 同子项目 2 | `null` | 同子项目 2 | 空 | `null` |

- `music = { file, events, energy }`：`file` 固定为 `music/music.wav`；`events` 来自 `music/events.json`；`energy` 来自 `music/analysis.json`（§4.3）。
- 输入类型（纯数据）：`GridInput(bpm, offset)`、`SectionInput(id, label, bars)`、`MomentInput(section_id, at, visual_action)`、`MusicInput(file, events, energy_hop, energy_values)`；`TimelineLayers` 的 `grid/moments/music` 字段改为这些类型，不再传入即报错。`LayerNotSupported` 保留给歌词。
- 校验（汇总成 `TimelineError`）：BPM 在 [40, 240]；`bars` 为正整数；`at` 可解析且落在本段内；`events` 名称非空、`kind` 为 `onset` 或 `sweep`、起止落在 [0, duration] 且 `start ≤ end`；音乐声明的 `duration` 与时间轴相差不超过 0.05 秒；短片中声明的 BPM 与节拍脚本相差不超过 0.01。

### 4.2 读取

`load_workspace_timeline` 改为接收 `TimelineSources`：

```
TimelineSources(root: Path, prefix: str = "", narration: bool, music_source: str, with_music: bool = True)
```

- `prefix=""` 读工作区顶层（成片、worker）；`prefix="upstream/"` 读上游物化目录（`prepare_turn`、预览端点）。两者之外不读别处。
- 短片读 `beatsheet/beatsheet.json`；有旁白读 `narrative/{narrative,timing}.json`；`music_source=synth` 且 `with_music` 时再读 `music/events.json` 与 `music/analysis.json`。
- `with_music=False` 给 `music` 阶段自己的 `prepare_turn` 用：生成不含 `music` 层的时间轴，作为合成脚本的输入。
- `LoadedTimeline` 增加 `base_hash`：不含 `music` 层的时间轴哈希（`music/render.json` 用它判断配乐是否对应当前时间轴）。`hash` 仍覆盖整条时间轴，含事件和能量。
- 项目形态（`narration`、`music_source`）由调用方从项目设置取，`timeline` 不读设置。

### 4.3 `music/analysis.json`

由 `render_music` 写入（工具托管文件），时间轴只读：

```
{ "hop": 0.1, "energy": [..], "duration": 15.0, "sample_rate": 44100,
  "waveform": [..], "metrics": { ... }, "wav_hash": "…" }
```

- `energy`：对单声道混音取 0.2 秒窗、0.1 秒步长的 RMS，dBFS 从 [-40, -6] 线性映射到 [0, 1]，截断，保留 3 位小数。绝对映射，不同项目之间可比。
- `waveform`：1000 个点的峰值包络，前端画波形用，不用解码音频。

## 5. `engines.render.html` 的运行时补全

`runtime.js` 的 `hit/energy/moment` 占位换成实现，并新增 `span`。所有返回时间都是**镜头局部秒**；`timeline.music` 为 `null` 时（无配乐的讲解）保持现行行为，`hit`、`energy` 恒为 0，`moment` 为 `undefined`，`span` 为空数组。

| 函数 | 语义 |
|---|---|
| `env.bt(n)`、`env.bar(n)` | 沿用：全局第 n 拍、第 n 小节（从 0 数）的时刻，换成局部秒 |
| `env.hit(name)` | 名为 `name`、`kind=onset` 的事件中，起点不晚于当前时刻的最近一个，之后的衰减包络：触发瞬间为 1，`exp(-Δt/0.18)`；之前为 0。名字不存在则报错并列出已有名称；对 `sweep` 类事件报错并提示用 `span` |
| `env.span(name)` | 名为 `name` 的全部事件 `[{ start, end }]`（局部秒，可落在镜头之外），不限 `kind` |
| `env.energy(lt?)` | 局部时刻 `lt`（缺省为当前）的能量，0–1，线性插值，越界取端点 |
| `env.moment(i)` | 本镜头第 i 个节拍脚本点 `{ at, t, action }`，`t` 为局部秒；越界抛 `RangeError` |

衰减常数 0.18 秒来自小试（`hit` 的手感合适，两个画面运行都用得对），写进提示词和 references。

## 6. `concept`、`beatsheet` 与 `animation_html` 的改动

### 6.1 `concept` 阶段

| 项 | 内容 |
|---|---|
| `name` / `allow_web` / `reads()` | `concept` / 是 / `[]` |
| 可写范围 | `concept/brief.md` |
| `artifact_dirs()` | `["concept"]` |
| 工具 | `web_search`、`fetch_url`（`stages.common.web_tools`）、`check_concept` |
| `finalize_blockers` | 重新运行 `check_concept`，有错误即阻止定稿 |
| `status_summary` | 已有章节数 / 总章节数 |

`brief.md` 的固定章节：`主题`（一句话）、`目标时长`（形如 `30 秒`，`check_concept` 要能解析出数字）、`情绪与能量走向`、`视觉母题`、`参考与灵感`、`段落草图`、`风险点`。`check_concept` 只检查章节齐全和目标时长可解析，不评价内容。

### 6.2 `beatsheet` 阶段

| 项 | 内容 |
|---|---|
| `name` / `allow_web` / `reads()` | `beatsheet` / 否 / `[concept, music]`（子项目 4 才会让 `music` 排在前面；短片里 `upstream_of` 只会得到 `concept`） |
| 可写范围 | `beatsheet/beatsheet.json` |
| 工具 | `validate_beatsheet`、`suggest_upstream_change` |
| `finalize_blockers` | 重新运行校验，有错误即阻止定稿 |
| `status_summary` | 段落数、BPM、总时长与目标时长 |

`beatsheet.json`（总设计 §7.2，短片部分）：

```
{ "bpm": 128,
  "sections": [ { "id", "label", "bars", "intent", "energy": "low|mid|high|peak",
                  "moments": [ { "at": "小节.拍", "visual_action" } ] } ] }
```

`validate_beatsheet` 的检查：

| 检查 | 级别 |
|---|---|
| JSON 合法、必填字段齐全、`energy` 取值 | 错误 |
| 段落 id 合法（沿用 `_ID_PATTERN`）且唯一；段落数 1–12 | 错误 |
| BPM 在 [60, 200]；`bars` 为正整数 | 错误 |
| 总时长与 `brief.md` 的目标时长相差超过 15% | 警告；超过 40% 为错误 |
| `moments[].at` 可解析、落在本段内、按时间顺序 | 错误 |
| 总时长不在 [8, 180] 秒 | 错误 |
| 总时长不是整数秒 | 不检查（128 BPM 下 8 小节恰好 15 秒只是巧合） |

### 6.3 `animation_html` 的改动

阶段定义、写入范围、工具名不变。变化：

- `prepare_turn`：按项目形态用 `TimelineSources(prefix="upstream/")` 生成 `upstream/timeline.json`；短片还会把 `upstream/beatsheet/beatsheet.json` 的段落意图留给 agent 读。不可用时仍写 `timeline.error.txt` 并删除旧文件，沿用子项目 2。
- **提示词**：单份 `prompt.md`，按 `timeline.json` 的 `narration` 是否为空分"有旁白"和"无旁白（短片）"两节；短片节写 `bt/bar/hit/span/energy/moment` 契约、`hit` 的 0.18 秒衰减、"所有时刻只能由 `env` 推出，不许写字面秒数"、节拍可见性不能全靠 HUD、冲击前留半拍静默的做法。
- **`validate_scenes_html`**：
  - 短片的敏感度检查换成"音乐平移"检查：**逐镜头渲染，且组装时不含 `global.js`**（`assemble` 新增 `include_global` 参数，默认真）；把 `grid`、`music.events`、`moments` 整体平移 0.2 秒，镜头自己的关键帧（强拍、事件起点、节拍脚本点）一帧都没变就是错误，部分没变是警告并点名。
  - 新增静态警告：`lt` 与数字字面量比较（`lt > 3.5`），提示"时刻必须来自 `env`"。已知盲区：部分字面量写死但整体仍响应 `env` 的镜头只靠这条警告和提示词。
  - 有旁白的镜头沿用 beat 敏感度检查，不变。
- **`render_preview_html`**：采样的必选点在短片里换成：镜头起止附近、每个节拍脚本点、每个强拍、出现次数最少的几个事件的起点（通常是冲击），再用均匀采样补到 16 张；其余（边界帧差、`pad` 重叠、图的形式）不变。
- `scene_checks`：沿用子项目 2B 的工具名与文本形状，不新增表。

## 7. `music` 阶段与 `engines.audio`

### 7.1 阶段定义

| 项 | 内容 |
|---|---|
| `name` / `allow_web` / `reads()` | `music` / 否 / `[concept, narrative, beatsheet]`（`upstream_of` 按流水线取交集：短片得到 `concept, beatsheet`，讲解得到 `narrative`） |
| 可写范围 | `music/compose.py` |
| 工具托管文件 | `music/music.wav`、`music/events.json`、`music/analysis.json`、`music/analysis.png`、`music/render.json` |
| 工具 | `render_music`、`suggest_upstream_change` |
| `artifact_dirs()` | `["music"]` |
| `prepare_turn` | 生成 `upstream/timeline.json`（`with_music=False`）；复制金样本 `upstream/exemplar/audio-techniques.py`（由探索作品 `audio.py` 整理，随阶段分发，作为技法参考）；时间轴不可用时写 `timeline.error.txt` |
| `finalize_blockers` | `music/render.json` 缺失；`compose.py` 的哈希与 `render.json` 不一致；当前时间轴的 `base_hash` 与 `render.json` 不一致；`music.wav` 缺失或哈希不一致 |
| `status_summary` | 是否已渲染、时长、BPM、事件数 |

`render.json`：`{ script_hash, base_hash, wav_hash, bpm, duration, rendered_at }`。`finalize_blockers` 只比对哈希，不重新运行脚本。

### 7.2 脚本契约

只约定输入输出，写法自由，只用标准库和 NumPy（`wave` 写文件）：

- 环境变量 `STUDIO_TIMELINE`：不含 `music` 层的时间轴 JSON；`STUDIO_OUT_WAV`；`STUDIO_OUT_EVENTS`。
- `events.json`：`{ "bpm", "duration", "events": [{ "name", "kind", "start", "end" }] }`，`kind` 为 `onset`（起音时刻在 `start`）或 `sweep`（持续的扫频，`start/end` 为起止）。
- 讲解形态的 `bpm` 由 agent 自选并声明；短片必须等于时间轴网格的 BPM。
- 可以读时间轴的 `grid`、`sections`、`moments`、`narration`，但**时刻必须由时间轴推出**，不许写死秒数（§7.4 自动检查）。

### 7.3 `engines.audio`（纯能力层）

位置 `backend/src/studio/engines/audio/`，只依赖 `config`、NumPy、Pillow；加 import-linter 契约（不 import 其他 `studio` 模块）。

| 模块 | 职责 |
|---|---|
| `runner.py` | `run_compose(script, timeline_path, out_dir, *, timeout, wrap_command) -> RunResult`：在临时目录里执行脚本，`cwd` 和环境变量指向该目录；`wrap_command` 由调用方传入（阶段层传入 Seatbelt 包装，`engines` 不 import `agent`）；超时、非零退出、缺产物都返回带 stderr 末尾若干行的错误；**产物先留在临时目录**，调用方校验通过后才移入 `music/` |
| `wav.py` | `read_wav(path)`：只用标准库和 NumPy，支持 PCM 16/24/32 位与 float32、单双声道、22050–96000 Hz；超限（文件大小、时长、采样率）报错 |
| `analysis.py` | `analyze(samples, sample_rate, timeline, events) -> MusicReport` |
| `picture.py` | `render_analysis_png(report, timeline, events) -> bytes`：波形、对数频率谱图、起音强度三行，叠加段落边界、小节线、事件标记（Pillow 自绘，谱图自带颜色表） |

`MusicReport` 的内容分两类：

**对齐类（可以当硬检查）**

| 项 | 规则 |
|---|---|
| 音频时长 | 与时间轴相差超过 0.05 秒为错误 |
| 声明的 `duration`、`bpm` | 与时间轴不一致为错误（讲解形态不检查 `bpm`） |
| 事件格式 | 同 §4.1 的事件校验 |
| 起音与网格对齐率 | 检测到的起音落在最近 1/16 拍 ±30 ms 内的比例，只报告，不设阈值 |
| 事件匹配率 | 只统计"可检测"的 `onset` 事件：起点晚于 50 ms，且不是 `sweep`；按事件名分项；落入"检测不到"（t=0 附近、被紧邻冲击掩蔽）的事件单独列出，不计入分母 |

**音量与观感类（只给警告和数字）**

| 项 | 规则 |
|---|---|
| 峰值与削波 | 削波样本数大于 0 为警告；峰值低于 -10 dBFS 为警告 |
| 整体 RMS | 短片目标 -16 到 -9 dBFS；背景乐目标 -30 到 -20 dBFS（旁白下还会再压低）；越界为警告 |
| 各段 RMS 与频谱重心 | 列出，供 agent 对照节拍脚本里每段的 `energy` |
| 能量走向 | 若节拍脚本里 `energy` 为 `low→peak` 的相邻段，实测 RMS 没有上升，警告 |

指标不评价"好不好听"，工具返回文字里固定附一句：音色、和声、混响量和声像无法由指标判断，需要用户试听。

### 7.4 `render_music`

一个工具，没有参数。流程：

1. `run_compose`，沙箱内运行；失败原样返回 stderr，不动 `music/` 里的旧产物。
2. 读 WAV 和 `events.json`，`analyze`；格式类错误直接失败。
3. **重定时校验**：用改过的时间轴再运行一次脚本并校验。短片把 BPM 改成原来的 0.8 倍（总长随之变为 1.25 倍）；讲解把各镜头时长整体乘 1.25（BPM 声明由脚本自定）。通过条件：音频时长与新时间轴相差不超过 0.05 秒、事件名集合不变、短片的起音对齐率不低于原来的一半。不通过是错误，信息写"脚本似乎写死了时间"。重定时运行的产物丢弃。
4. 通过后，把产物移入 `music/`，写 `analysis.json`、`analysis.png`、`render.json`；通过 `record_tool_write` 登记工具托管文件。
5. 返回：一张 PNG（`analysis.png`）加文本（时长、峰值与削波、整体与分段 RMS、起音与网格对齐率、事件匹配率分项、检测不到的事件、警告、"需要用户试听"一句）。

沙箱：`sandbox_available()` 为假时返回"当前平台没有沙箱，不能运行合成脚本"，不降级到无沙箱运行。Seatbelt 配置沿用 Shell 的（禁网、禁读仓库与数据目录、只放行工作区与专用临时目录的写）；脚本在 `.cache/tmp` 的子目录里运行，所以写到 `music/` 之外的文件会被本轮的越界检查拦下。再设 `RLIMIT_CPU`；WAV 与 `events.json` 有大小上限（数值在计划里定）。

### 7.5 提示词（`prompt.md`，中文）

- 输入：`upstream/timeline.json`、`upstream/concept/brief.md`、`upstream/beatsheet/beatsheet.json`（短片）或 `upstream/narrative/narrative.json`（讲解）、金样本。
- 契约：§7.2；"你听不到声音，只能靠 `render_music` 的图和指标判断"；指标只证明对齐，**不能用指标当作音乐好听的证据**，收尾必须说明哪些东西无法验证。
- 短片：按节拍脚本每段的 `energy` 和 `moments` 编排；冲击前留半拍静默；事件命名建议（`kick`、`clap`、`hat`、`bass`、`stab`、`impact`、`riser`……），画面端靠名字对齐，名字要稳定。
- 讲解：做铺底的背景乐，不抢旁白，不要有人声感的旋律和密集高频；整体 RMS 目标更低。
- 工作流：先搭节奏骨架（鼓与贝斯），渲染看图，再加铺底、效果和后期；每次改动都渲染一次并看图。

## 8. 成片混音与 worker（3B）

### 8.1 `engines.render.mix`

`mix_final` 的 `music` 参数不再抛 `NotImplementedError`。`AudioTrack` 增加 `gain_db: float = 0.0`；新增 `MusicMix(track, duck_under_narration, fade_in, fade_out)`（具体形状在计划里定）。

- **只有配乐（短片）**：配乐重采样到 44.1 kHz 立体声，`apad=whole_dur` + `atrim` 钉住时长，加 15 ms 首尾淡变防止爆音，输出 AAC。
- **旁白 + 配乐**：旁白轨按子项目 2B 拼成一条总线并 `asplit`；配乐经 `sidechaincompress`（阈值、比例、起落时间在计划里实测后定）以旁白总线为侧链，再与旁白 `amix normalize=0`；配乐先乘 `gain_db`（讲解默认 -8 dB），首淡入 1 秒、尾淡出 1.5 秒。
- 其余沿用：临时文件加原子改名、`-t` 钉时长、`+faststart`、`stdin` 显式指定。

### 8.2 `worker_html`

- 时间轴读取改用 `TimelineSources(prefix="")` 并按项目 `narration`/`music_source` 选来源；短片没有旁白轨，音轨只有配乐。
- 前置检查新增：`music/music.wav`、`music/events.json`、`music/analysis.json` 存在；`render.json` 的 `base_hash` 与当前时间轴一致（否则点名"配乐与当前时间轴不一致，需要在配乐阶段重新渲染"）。
- 画面缓存键不变，`timeline_hash` 已覆盖事件和能量；音频不进缓存，每次重混。
- `final.json`：`audio_sources` 增加配乐文件的哈希，`engine`、`timeline_hash` 等字段不变。

## 9. api 与前端（3B）

### 9.1 api

- `GET /api/projects/{id}/music/meta`：`{ hash, duration, bpm, events, waveform, metrics, rendered }`；没有产物时 `rendered=false`。
- `GET /api/projects/{id}/music/audio`：返回 `music.wav`，支持 `Range`，`Cache-Control: no-store`，路径走 `workspace` 的安全解析。
- `POST /api/projects/{id}/music/render`：不经 agent，直接运行与 `render_music` 同一份核心逻辑，返回报告（含图的 base64）；有轮次在跑时返回 409；沙箱不可用返回 409 加原因。
- `GET .../html-preview/meta` 增加 `music: { url, gain } | null`；`html-preview` 的时间轴改用 `TimelineSources(prefix="upstream/")`，与 agent 看到的一致。

### 9.2 前端

- **`MusicCanvas`**（`features/canvas/music/`）：三个标签。
  - 播放：音频播放器、`waveform` 波形（画在 canvas 上）、段落与事件标记（点击跳转）、`analysis.png`、指标摘要，以及"需要用户试听"的提示；
  - 脚本：`CodeEditor`（python），保存走现有文件保存，阶段为 `music`；旁边有"渲染"按钮调 `POST .../render`；
  - 事件：事件表（名称、类型、起止），点击跳转。
- `ProjectWorkbenchPage` 的阶段分发新增 `music`；`concept`、`beatsheet` 走现有的 `FileCanvas`，定稿按钮沿用通用阶段的位置。
- **实时预览播放**：`useHtmlPlayback` 增加配乐来源。短片：没有旁白片段、有配乐，配乐的 `currentTime` 是时钟，整片循环或按段循环；讲解 + 背景乐：旁白片段仍是时钟，配乐用另一个 `Audio` 低音量跟随（镜头切换时按全局时间对齐），预览允许有小偏差，以成片为准。
- 创建项目对话框与阶段导航不需要改：阶段注册后 `video_kinds.unavailable_reason` 自动放开短片和"讲解 + 合成背景乐"。

## 10. 测试策略

- **纯函数**：`build_timeline` 三种来源与错误汇总；`TimelineSources` 读取（顶层与 `upstream/`、缺文件、符号链接越界）；`base_hash` 随事件变化而不变；`validate_beatsheet`、`check_concept` 表驱动；`wav.read_wav`（各格式、超限）；`analysis.analyze`（用合成的已知 BPM 测试音频：对齐率、事件匹配、检测不到的分类、能量曲线映射）；`picture` 的尺寸与不崩；`hit/span/energy/moment` 的语义。
- **`slow`**：真实 Chromium 上 `env` 四个函数在极小固定场景里的取值；音乐平移检查（含与不含 `global.js` 的对比）；真实 ffmpeg 侧链混音的时长与音轨，并用 `astats` 验证旁白段背景乐被压低；`run_compose` 在真实 Seatbelt 沙箱里运行并拦截越界写、超时。
- **阶段与 API**：fake 运行时分别跑通短片和"讲解 + 合成背景乐"的整条流水线，产物齐全且能定稿；`render_music` 的失败路径（脚本抛错、缺产物、超时、重定时不通过、沙箱不可用）都不改动旧产物；音乐端点与 409；worker 的前置检查与 `final.json` 字段。
- **联调**：一个阶段层测试把 `render_music` 的真实产物（用固定的参考合成脚本）读成时间轴，再喂给 `animation_html` 的 `prepare_turn` 与 `validate_scenes_html`，覆盖"`events.json` → 时间轴 → `env`"整条路径。
- **前端**：vitest 覆盖配乐时钟映射、波形与事件标记坐标、播放来源切换；`MusicCanvas` 组件测试。L4 由控制者在浏览器中验证：创建短片项目、四个阶段的导航、配乐画布试听、实时预览。
- **真实模型冒烟**（`claude-login`）：3A 一个短片小项目（2 段 × 2 小节，约 7.5 秒）走到画面校验通过；3B 再出成片并校验音轨。断言流程与产物形状，不评价观感。

## 11. 新增依赖与资产

- **依赖**：`numpy>=2,<3` 声明为直接依赖（目前由 manim 间接带入，版本 2.5.3）；不引入 librosa、scipy、matplotlib。Pillow 已有。
- **资产**：`stages/music/exemplar/audio-techniques.py`（由探索作品 `audio.py` 整理）；三个阶段的 `prompt.md`。

## 12. 对总设计的补充与修订

| 总设计位置 | 变化 |
|---|---|
| §4.2 来源表 | 新增 `music/analysis.json`（能量、波形、指标，工具托管）；`music/events.json` 由脚本在沙箱临时目录写出，校验通过后才移入 `music/` |
| §4.3 | 讲解 + 合成背景乐的 `grid` 取自 `events.json` 声明的 `bpm`；时间轴 `base_hash`（不含 `music` 层）用于判断配乐是否对应当前时间轴 |
| §5.1 `env` | 新增 `env.span(name)`；`hit` 对 `sweep` 事件报错；`hit` 的衰减常数定为 0.18 秒 |
| §5.3 | 敏感度检查对短片改为逐镜头、不含 `global.js` 的"音乐平移"检查；新增字面量时刻的静态警告 |
| §6.1 | `render_music` 增加重定时校验；产物校验通过前不写回；画图用 Pillow 而非 matplotlib；指标分对齐类与观感类 |
| §7.1 | `brief.md` 增加固定章节 `目标时长`，供 `validate_beatsheet` 比对 |
| §8 | 配乐音量常量：讲解背景乐默认 -8 dB，侧链参数在 3B 计划里实测后定；短片配乐不加增益 |
| §12 风险 | "agent 听不到声音"已由小试回答：结构、节奏、动态靠谱图迭代，音色靠用户试听；不再需要加强指标 |

## 13. 延后事项与风险

**记入 `docs/plans/TODO.md`**：`concept`、`beatsheet` 的专用画布；音乐阶段的手动渲染如果需要进度反馈可改为任务；侧链压低参数的听感校准；音乐导入与 MV（子项目 4）。

| 风险 | 验证方式 |
|---|---|
| 非 macOS 没有沙箱，不能运行合成脚本 | 失败关闭并给出明确错误；项目只在 macOS 上使用 |
| 脚本死循环或占满内存 | 超时、`RLIMIT_CPU`、输出大小上限；内存上限在 macOS 上无法强制，计划里评估 |
| 指标被刷（为了对齐率而扭曲音乐） | 提示词明确指标不是质量证明；用户试听是最终判断；小试已有一例（对扫频加网格门限） |
| 侧链压低的听感 | 3B 用 `astats` 验证数值，听感由负责人验收时判断，记入 references |
| 重定时校验使一次渲染耗时翻倍 | 合成脚本通常 1 秒左右；超过 60 秒时报告里提示 |
| 配乐重新渲染后画面阶段变旧 | 现有 stale 机制；`render.json` 的哈希保证配乐与时间轴一致 |
| 一次短片小试的成本是 $7–11 | 提示词按镜头迭代；不加系统层限制，沿用 2 的决定 |
