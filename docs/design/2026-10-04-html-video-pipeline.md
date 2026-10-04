# 多形态视频流水线：项目类型、HTML 引擎与配乐阶段

状态：已批准（2026-10-04）。本文是新增设计，不修改 `2026-09-26-architecture.md`；与已批准设计前提冲突的部分（"第一版只实现 manim"、固定三阶段、静态上下游）由 [ADR 0020](../decisions/0020-阶段流水线按项目配置派生.md) 和 [ADR 0021](../decisions/0021-HTML引擎与配乐阶段.md) 取代。

## 1. 背景与目标

系统目前只做一种视频：有旁白的 Manim 知识讲解（选题 → 叙事 → 动画）。`docs/temp/` 里的探索作品（`reel/reel.html`、`reel/audio.py`、`op.md`）验证了另一种做法：

- 画面是 Canvas 2D 上的纯函数 `render(t)`，实时播放与逐帧导出完全一致；
- 配乐由 NumPy 从波形合成，所有画面动作对齐同一套节拍网格；
- Playwright 驱动无头 Chromium 逐帧取图，经管道交给 ffmpeg 编码；
- 抽帧拼缩略图总览 → 检查 → 修改的回路。

**目标**：把这种做法流程化地融入系统，与 Manim 并存。创建项目时由用户决定视频类型、是否有旁白、配乐来源（无 / 代码合成 / 导入音乐），覆盖四种形态：

| 预设 | 引擎 | 旁白 | 配乐 |
|---|---|---|---|
| 知识讲解（Manim） | manim | 有 | 无 / 合成 |
| 知识讲解（HTML） | html | 有 | 无 / 合成 |
| 动态图形短片 | html | 无 | 合成 |
| 音乐 MV | html | 无 | 导入 |

**已确认的前提：**

| 项 | 决定 |
|---|---|
| 配乐来源 | 无 / 代码合成 / 导入；AI 音乐服务（Suno 等）以后作为新来源加入，与"导入"共用分析路径 |
| 歌词 | 第一版不做；时间轴为歌词层预留位置 |
| 讲解视频 + 背景乐 | 背景乐只做铺底，画面切换不吸附节拍（不卡点），旁白节奏优先 |
| 项目配置 | 创建后锁定；换类型就新建项目（ADR 0017 允许一张选题建多个项目） |
| HTML 绘制 | 只支持 Canvas 2D；系统**不提供绘图/缓动运行时库**，只提供挂载壳与时间轴取数，技法由 agent 自由发挥 |
| 新依赖 | `playwright`（含 Chromium）、`librosa` |

**非目标**：歌词对齐与 ASR；变速曲；DOM/CSS 动画与 WebGL；讲解视频卡点；AI 音乐服务；创建后修改项目类型。

## 2. 项目配置

### 2.1 字段

`projects.settings` 新增：

| 字段 | 取值 | 说明 |
|---|---|---|
| `video_kind` | `explainer_manim` / `explainer_html` / `motion_reel` / `music_video` | 预设，仅用于界面展示和默认值 |
| `engine` | `manim` / `html` | 渲染引擎 |
| `narration` | `true` / `false` | 是否有旁白 |
| `music_source` | `none` / `synth` / `import` | 配乐来源 |
| `pipeline` | 阶段 key 列表 | 创建时由 `build_pipeline` 派生并写入，之后不再重算 |

### 2.2 合法性规则

- `narration=false` 时 `music_source` 不能是 `none`（必须有时间轴来源）。
- `narration=false` 时 `engine` 只能是 `html`（Manim 的时间控制建立在逐镜头配音时长上）。
- 创建时只选定"导入"这一来源；音乐文件在配乐阶段的画布里上传。

规则由后端校验（创建接口 422），前端用同一套规则禁用非法组合。

### 2.3 锁定与兼容

- 以上字段创建后只读；项目设置对话框里只展示。
- 缺这些字段的老项目一律视为 `engine=manim, narration=true, music_source=none, pipeline=[topic, narrative, animation]`，不做数据迁移。

## 3. 阶段流水线

### 3.1 阶段 key

阶段按变体拆成不同 key，界面上共用显示名；现有 key 不改。

| key | 显示名 | 适用 | 产物目录 |
|---|---|---|---|
| `topic` | 选题 | 有旁白 | `topic/`（不变） |
| `concept` | 创意 | 无旁白 | `concept/` |
| `narrative` | 叙事 | 有旁白 | `narrative/`（不变） |
| `beatsheet` | 节拍脚本 | 无旁白 | `beatsheet/` |
| `music` | 配乐 | 有配乐 | `music/` |
| `animation` | 动画 | manim | `animation/`（不变） |
| `animation_html` | 动画 | html | `animation/` |

一个项目只会有 `animation` 与 `animation_html` 之一，二者共用 `animation/` 目录，成片面板与输出路径保持一致。

### 3.2 `build_pipeline(config) -> list[str]`

纯函数，创建项目时调用一次，结果写入 `settings.pipeline`，并按此顺序创建 `project_stages` 行。原则：**谁定时间，谁排在前面**。

| 配置 | 流水线 |
|---|---|
| 讲解，无配乐 | `topic → narrative → animation`（或 `animation_html`） |
| 讲解 + 合成背景乐 | `topic → narrative → music → animation`（或 `animation_html`） |
| 动态图形短片 | `concept → beatsheet → music → animation_html` |
| 音乐 MV | `concept → music → beatsheet → animation_html` |

### 3.3 上下游解析

- `StageDefinition.upstream_stages()` 改为 `reads() -> list[str]`：阶段声明"可能读取哪些阶段的产物"。例如 `animation_html.reads() = [narrative, beatsheet, music]`，`music.reads() = [concept, narrative, beatsheet]`，`beatsheet.reads() = [concept, music]`。
- `agent` 层新增 `upstream_of(pipeline, registry, stage)`：`reads()` 与项目流水线取交集，且只保留在流水线中排在它前面的阶段。例：短片里 `music` 的上游是 `concept` 与 `beatsheet`；MV 里 `music` 的上游只有 `concept`（`beatsheet` 排在它之后），`beatsheet` 的上游是 `concept` 与 `music`。
- `stage_flow`（定稿、stale）、`upstream/` 副本刷新、回退建议（"只能向直接上游提"）、前言中的上游摘要都改为调用 `upstream_of`。它只依赖阶段协议与项目配置，不违反"agent 不 import stages"。

### 3.4 新钩子 `prepare_turn`

`StageDefinition` 新增可选方法 `prepare_turn(workdir: Path) -> None`。TurnRunner 在每轮开始、刷新 `upstream/` 之后调用，供阶段生成本轮需要的只读派生文件（见 §4.4）。默认实现为空。

### 3.5 前端

- 创建项目对话框（项目页与选题池两处入口）新增"视频类型"：四个预设卡片，选中后可展开微调三个开关，非法组合禁用并说明原因。
- `StageNav` 按 `pipeline` 渲染阶段列表；画布按阶段 key 分发到对应组件。
- 项目信息对话框展示类型与三个开关。

## 4. 统一时间轴

### 4.1 目标

消费时间的阶段（`music`、`animation_html`）不关心时间权威是谁，只读一份结构固定的 `timeline.json`。Manim 路径不变，仍直接读 `narrative/timing.json`。

### 4.2 分层来源

| 层 | 来源文件 | 谁写 |
|---|---|---|
| 旁白 `narration` | `narrative/timing.json`（现有） | `synthesize_tts` |
| 段落与网格（短片） | `beatsheet/beatsheet.json` | agent，`validate_beatsheet` 校验 |
| 网格、能量（MV） | `music/analysis.json` | `analyze_music` |
| 段落（MV） | `music/sections.json` | agent，`validate_sections` 校验 |
| 音乐事件 | `music/events.json` | 合成脚本运行时输出 |
| 歌词 `lyrics` | 预留 | 第一版恒为空 |

### 4.3 结构与合并规则

```
duration
grid      { bpm, offset, beats[], downbeats[] } | null
sections  [{ id, label, start, end }]
narration [{ scene_id, start, end, beats[{ start, end, cue_text }] }]
moments   [{ section_id, at, t, visual_action }]      # 来自 beatsheet，at 为音乐记法，t 为换算后的秒
music     { file, events[{ name, kind, start, end }], energy{ hop, values[] } } | null
lyrics    []
```

- **有旁白**：`sections` 即镜头，起点为前序镜头配音时长累加；有合成背景乐时 `grid` 仅作铺底参考。
- **短片**：网格由 `beatsheet` 决定，段落时长 = `bars × 4 × 60 / bpm`；`music` 必须按此网格产出（校验 `events.json` 声明的 BPM 与总长一致）。
- **MV**：网格来自 `analysis.json`，段落来自 `sections.json`（含可选截取区间 `range`，时间轴以截取起点为 0）；`beatsheet` 只能引用段落 id。
- 时间轴是**累积**的：每个阶段只看到上游已产出的层。

### 4.4 实现位置

- 新增纯能力模块 `studio.timeline`：Pydantic schema、`build_timeline(layers) -> Timeline`、"小节.拍"记法换算（如 `3.2`、`4.1+1/16`）。只依赖 `config`，加一条 import-linter `forbidden` 契约。
- `music`、`animation_html` 在 `prepare_turn` 里用上游**定稿版本**生成 `upstream/timeline.json`（只读、不进快照，语义同 `upstream/` 其余内容）。
- 成片渲染时用定稿快照重新计算时间轴，把哈希写入 `output/final.json`。

## 5. HTML 渲染引擎与 `animation_html` 阶段

### 5.1 场景写法

```
animation/
  scenes/<section_id>.js   # 每段一个文件，导出 { draw(ctx, lt, env), pad? }
  lib/*.js                 # 可选：agent 自建、自维护的项目内复用代码
  global.js                # 可选：全局后期 post(ctx, t, env)
  assets/*                 # 可选：agent 制作的 SVG/图片
```

- `lt` 为段内局部时间；`env` 提供画布尺寸、全局 `t`、本段 `start`/`end`、时间轴数据，以及几个纯取数函数：`bt(n)`（第 n 拍时刻）、`bar(n)`、`hit(name)`（命名事件之后的衰减包络）、`cue(i)`（第 i 个旁白 beat 时刻）、`energy(t)`、`moment(i)`。
- `pad: { in, out }` 允许本段提前/延后绘制以做转场，合成器按段顺序叠画重叠部分。
- 段之间不共享可变状态（一切是 `t` 的纯函数），结构上避免 ADR 0015 中跨镜头 `self.xxx` 依赖的问题。

### 5.2 不提供运行时库

系统只负责页面组装、`renderAt(t)` 契约和 `env`。缓动、形变、粒子、后期等技法全部由 agent 编写；项目内复用放 `animation/lib/`。需要"起点"时通过风格库的 `exemplars/` 提供金样本（例如 `reel.html`），agent 借鉴而不受 API 约束。

字体只允许本地 woff2：系统自带一组基础字体（含中文），以及风格目录 `style/fonts/`。引擎在 `document.fonts` 就绪后才出帧。

### 5.3 确定性约束（`validate_scenes_html`）

- **静态检查**：禁止 `Math.random`、`Date`、`performance.now`、`requestAnimationFrame`、`setTimeout`/`setInterval`、`fetch`/`XMLHttpRequest`、外部 URL。
- **冒烟运行**：无头加载组装页，在若干采样时刻调用 `renderAt`，收集异常与 console 报错，报告段 id、时刻与 JS 堆栈。

### 5.4 引擎 `engines.render.html`（纯能力层，只依赖 `config`）

- **组装**：把字体、`timeline.json`、`lib/`、各段脚本、`global.js` 拼成 `index.html`，暴露 `window.renderAt(t)` 与 `window.ready`。
- **出帧**：Playwright + 无头 Chromium，`page.route` 直接从目录供给文件（不开端口）；逐帧 `renderAt(i / fps)` 取 JPEG，经管道交给 ffmpeg（libx264、yuv420p）输出**无声**视频；fps 与分辨率取项目设置。
- **参考性能**：reel 1080p60 900 帧约 22 秒。

### 5.5 预览 `render_preview_html(section_id)`

不渲染视频：在关键时刻（本段强拍、命名事件、旁白 beat 结束点，加均匀采样）调用 `renderAt` 截图，拼成一张缩略图总览返回给 agent，同时返回脚本报错。`supports_vision=false` 时只返回文本指标。在 api 进程中执行，常驻一个预热的浏览器实例，有并发上限。

### 5.6 前端实时预览

动画画布新增"实时预览"标签：sandbox iframe 加载同一份组装页（api 从工作区提供），画面以音频播放时间为准（配音拼轨或配乐），支持拖动、逐段循环，产物变化后自动刷新。

### 5.7 阶段定义

| 项 | 内容 |
|---|---|
| reads | `narrative`、`beatsheet`、`music`，外加 `upstream/timeline.json` |
| 可写范围 | `animation/scenes/*.js`、`animation/lib/*.js`、`animation/global.js`、`animation/assets/*` |
| 工具 | `validate_scenes_html`、`render_preview_html`、`suggest_upstream_change`、Shell |
| 提示词 | `env` 契约、确定性规则、布局原则（沿用 Manim 提示词中的布局骨架、转场不留中间态等） |
| 定稿条件 | 同 `animation`：`final.json` 对应当前最新快照，用户确认 |

## 6. 配乐阶段（`music`）

一个阶段，按 `music_source` 切换提示词、工具与画布。

### 6.1 合成形态

| 文件 | 谁写 | 说明 |
|---|---|---|
| `music/compose.py` | agent | NumPy 合成脚本，写法自由 |
| `music/music.wav`、`music/events.json` | `render_music` | 音频与命名事件 |
| `music/render.json` | `render_music` | 脚本哈希、时间轴哈希 |

- **脚本契约**（只约定输入输出）：环境变量 `STUDIO_TIMELINE`（时间轴路径）、`STUDIO_OUT_WAV`、`STUDIO_OUT_EVENTS`（`[{name, kind, start, end}]`，另含声明的 `bpm`、`duration`）。
- **`render_music`**：沙箱子进程执行脚本（超时），写回产物，返回：
  - 一张图：波形 + 频谱图，叠加段落边界、节拍网格、事件标记；
  - 指标：时长与时间轴是否一致、峰值与削波次数、整体响度、各段能量、起音点与网格的对齐率；有旁白时检查铺底响度是否在目标范围。

### 6.2 导入形态

- 用户在配乐画布上传音频，api 写入 `music/source.<ext>`（大小上限，格式白名单）。
- **`analyze_music`**（librosa）生成 `music/analysis.json`：BPM、拍点、强拍（按 4/4 推断）、候选段落边界、能量曲线、置信度；返回与合成形态同款的分析图。
- agent 编写 `music/sections.json`：段落 id、标签、起止（必须落在强拍上）、可选截取区间 `range`。自动分段常不准，修正写在内容层，不改派生数据。
- **`validate_sections`**：段落不重叠、对齐强拍、在音频范围内。

### 6.3 共用

- **画布**：播放器 + 波形，段落/事件标记可点击跳转；合成形态附脚本编辑器，导入形态附上传区。
- **定稿条件**：合成——`render.json` 与当前脚本、当前时间轴一致；导入——分析结果对应当前源文件哈希，且 `sections.json` 校验通过。
- 重新定稿后下游（MV 的 `beatsheet`、`animation_html`）走现有 stale 机制。

## 7. `concept` 与 `beatsheet` 阶段

### 7.1 `concept`（创意）

- **产物**：`concept/brief.md`，固定章节：主题/一句话；情绪与能量走向；视觉母题（形状、配色、质感）；参考与灵感；段落草图；风险点。
- **工具**：联网工具（`stages.common.web_tools`）、`check_concept`（只检查章节齐全）。
- **定稿条件**：`check_concept` 无错误，用户确认。

### 7.2 `beatsheet`（节拍脚本）

`beatsheet/beatsheet.json`（agent 编写）：

```
bpm                              # 仅短片；MV 中不允许出现
sections[{
  id, label,
  bars                           # 仅短片；MV 中改为 ref：music/sections.json 的段落 id
  intent, energy                 # energy: low / mid / high / peak
  moments[{ at, visual_action }] # at 用"小节.拍"记法，相对本段
}]
```

- `moments.at` 用音乐记法而非秒：改 BPM 不用改脚本，秒数由时间轴换算。
- **`validate_beatsheet`**：短片——BPM 在合理范围，总长与目标时长偏差在阈值内；MV——每个 `ref` 存在于上游 `sections.json` 且顺序一致；所有 `at` 落在本段范围内。
- **定稿条件**：校验通过。

叙事回答"说什么"（时间来自配音）；节拍脚本回答"什么时候发生什么"（时间来自音乐网格）。两者都不写代码。

## 8. 成片合成

worker 的 `final_render` 任务按引擎分两步：

1. **画面**：Manim 维持 ADR 0015 的整体渲染（配音已嵌入）；HTML 引擎输出无声视频，进度按帧数报告真实百分比。
2. **音频混合**（新步骤，ffmpeg）：
   - HTML + 旁白：按 `timeline.narration` 起点用 `adelay` + `amix` 拼旁白轨；
   - 有旁白 + 背景乐：背景乐以旁白为侧链 `sidechaincompress` 压低，首尾淡入淡出；Manim 成片以其自带音轨作侧链；
   - MV：按 `sections.json` 的 `range` 截取；
   - 统一 AAC，`-movflags +faststart`。

缓存键：引擎、引擎版本、画面源码哈希、时间轴哈希、音频源哈希、画质。`output/final.json` 新增 `timeline_hash`、`audio_sources`。

## 9. 错误处理

| 情况 | 处理 |
|---|---|
| Chromium 未安装 / 启动失败 | 工具与任务返回明确错误并附安装命令；环境自检只警告 |
| 场景脚本运行时异常 | 预览与成片返回段 id、时刻、JS 堆栈 |
| 合成脚本超时 / 异常 / 无输出 | stderr 原样返回 agent，不写回产物 |
| 音频分析置信度低（散拍、变速） | 返回置信度，提示手动调整 `sections.json`；变速曲第一版不支持 |
| 上游时间轴变化而下游未跟上 | 现有 stale 机制；下游前言附时间轴变化摘要（段落增减、时长变化） |
| 上传文件过大 / 格式不支持 | api 422，画布提示 |

## 10. 测试策略

- **纯函数单测**：`build_pipeline` 的合法与非法组合、`upstream_of`、`build_timeline` 三种时间权威、音乐记法换算、各校验器。
- **能力层**：HTML 引擎用极小固定场景做截帧测试（`slow`）；`analyze_music` 用已知 BPM 的合成测试音频；混音检查时长与音轨。
- **阶段层**：fake 运行时跑通四种预设的完整流水线，产物齐全且能定稿。
- **L4 浏览器验证**：创建项目的类型选择、动态阶段导航、配乐画布、实时预览。
- **真实模型冒烟**：每种预设一个小项目。

## 11. 实施顺序

四个子项目，各自一份实施计划，每个都独立交付可用能力：

| 顺序 | 子项目 | 内容 | 交付后可用 |
|---|---|---|---|
| 1 | 项目类型与流水线 | 配置字段与规则、`build_pipeline`、`reads`/`upstream_of`、`prepare_turn`、创建项目的类型选择、动态阶段导航 | 现有 Manim 流程不受影响，地基就位 |
| 2 | 时间轴 + HTML 引擎 | `studio.timeline`、`engines.render.html`、`animation_html`、实时预览、HTML 成片与旁白拼轨 | 知识讲解（HTML） |
| 3 | 配乐（合成） | `music` 合成形态、`concept`、`beatsheet` 短片部分、背景乐混音 | 动态图形短片、讲解 + 背景乐 |
| 4 | 配乐（导入） | 上传、`analyze_music`、`sections.json`、`beatsheet` MV 部分 | 音乐 MV |

## 12. 风险与早期验证项

| 风险 | 验证方式 |
|---|---|
| agent 在无运行时库的情况下写 Canvas 动画的质量与稳定性 | 子项目 2 开始前用真实模型做一次小 spike：给 `env` 契约与一个金样本，写 2–3 段并预览 |
| agent 听不到声音，合成配乐的音乐性 | 子项目 3 早期验证频谱图 + 指标自检是否足以支撑迭代；不足则加强指标或依赖用户试听反馈 |
| librosa 强拍与分段在流行歌曲上的准确率 | 子项目 4 开始前用 3–5 首不同风格的歌实测，结论写进 `docs/references/` |
| Playwright 在 api 进程内常驻浏览器的资源占用与稳定性 | 子项目 2 中测量，必要时改为按需启动或移到子进程 |
| 长视频（4 分钟 MV）的出帧时长 | 子项目 2/4 中实测，结论写进 `docs/references/` |
