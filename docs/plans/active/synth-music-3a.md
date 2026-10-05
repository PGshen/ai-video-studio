# synth-music-3a：合成配乐与动态图形短片的 agent 侧（多形态视频 子项目 3A）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 进行中 |
| 里程碑 | 多形态视频流水线 · 子项目 3/4 · 计划 3A |
| 设计依据 | [子项目 3 设计](../../design/2026-10-05-synth-music-reel.md)（已批准）；[总设计](../../design/2026-10-04-html-video-pipeline.md) §4–§7；[ADR 0021](../../decisions/0021-HTML引擎与配乐阶段.md)；[ADR 0009](../../decisions/)（沙箱）；[小试结论](../../references/motion-reel-spike.md) |
| 分支 | `synth-music-3a` |
| 批准记录 | 2026-10-05：负责人确认范围（短片与"讲解 + 合成背景乐"都做）、批准设计；设计批准后直接写计划并按计划实现，不另等计划审批 |

> 执行方式：Native（自己按任务顺序实现），整分支完成后由一个独立评审者评审一次。本计划的「进度」「决策记录」就是账本。每个任务先写失败的测试，再实现。计划只写结构和意图，不写完整实现代码。

## 目标

两种形态能在 agent 侧走完整条流水线：动态图形短片（`concept → beatsheet → music → animation_html`）和"讲解 + 合成背景乐"（`topic → narrative → music → animation_html`）。创建这两类项目可用；agent 能写概念、节拍脚本，能写 NumPy 配乐脚本并用 `render_music` 的图与指标自检，能按节拍写画面并用校验、预览工具自检。本计划**不含**成片混音（背景乐侧链）、音乐 api、音乐画布、预览播放改造（计划 3B）；`music` 阶段在前端暂时落到通用文件画布。Manim 路径、无配乐的讲解和老项目行为不变。

## 范围

**包含：**

- `studio.timeline`：补 `grid`、`moments`、`music` 三层；`TimelineSources` 按项目形态读取（顶层与 `upstream/` 两种前缀）；`base_hash`；调用方（`worker_html`、`api/html_preview`、`animation_html.prepare`）适配新签名，行为不变。
- `engines.audio`（纯能力层，新增直接依赖 numpy）：WAV 读取、`analyze`（对齐类与观感类指标、能量曲线、波形包络）、Pillow 自绘分析图、`run_compose` 脚本运行器。
- 阶段 `concept`、`beatsheet`、`music`：定义、工具（`check_concept`、`validate_beatsheet`、`render_music`）、提示词、`prepare_turn`、`finalize_blockers`、金样本；`main.py` 注册。
- HTML 运行时：`env.hit/span/energy/moment` 实现；`assemble(include_global=…)`。
- `animation_html`：`prepare_turn` 按形态生成时间轴；`validate_scenes_html` 与 `render_preview_html` 的短片分支；提示词短片节。
- 测试：纯函数、`slow` 的真实 Chromium / Seatbelt、fake 运行时的两条整流水线集成测试、联调测试、一个真实模型冒烟（短片，到画面校验通过）。
- 文档同步：ARCHITECTURE、QUALITY、runbook、references、TODO。

**不包含（3B 或更后）：**

- `engines.render.mix` 的 `music` 轨、`worker_html` 的前置检查与 `final.json` 新字段、成片冒烟。
- `/music/*` 端点、`html-preview/meta` 的 `music` 字段、`MusicCanvas`、`useHtmlPlayback` 的配乐来源。
- `concept`、`beatsheet` 的专用画布；音乐导入与 MV；歌词；变速曲。

## 全局约束

- 设计 §4.1 的时间轴来源表是权威：短片的 `sections` 来自 `beatsheet.json`（时长 = `bars × 4 × 60 / bpm`），网格 `offset=0`、每拍一个时刻、每 4 拍一个强拍、覆盖整片再多一拍；讲解 + 背景乐的网格取自 `events.json` 声明的 `bpm` 与 `offset`；无配乐的讲解 `grid` 与 `music` 都为 `null`。
- `studio.timeline` 仍只依赖标准库和 pydantic；schema 字段不改；`LayerNotSupported` 只保留给歌词。
- `engines.audio` 只依赖 `config`、NumPy、Pillow，不 import 其他 `studio` 模块，也不 import `agent`；沙箱包装由阶段层传入。
- 沙箱：复用 `agent.shell_sandbox`（Seatbelt）；`sandbox_available()` 为假时 `render_music` 返回错误，不降级到无沙箱运行；脚本超时 120 秒，另设 `RLIMIT_CPU`；脚本只用标准库和 NumPy。
- `render_music` 的产物先留在 `.cache/tmp` 下的临时目录，校验通过后才移入 `music/`；任何失败都不改动 `music/` 里的旧产物。
- 能量曲线：对单声道混音取 0.2 秒窗、0.1 秒步长的 RMS，dBFS 从 [-40, -6] 线性映射到 [0, 1]，截断，保留 3 位小数；波形包络 1000 个点。
- 对齐类检查：音频时长与时间轴相差不超过 0.05 秒；起音对齐按 1/16 拍 ±30 ms；事件匹配按 ±40 ms，只统计起点晚于 50 ms 的 `onset` 事件。
- 重定时校验：短片 BPM 乘 0.8、讲解各镜头时长乘 1.25；通过条件见设计 §7.4。
- `env` 契约按设计 §5：`hit` 衰减常数 0.18 秒，名字不存在报错并列出已有名称，对 `sweep` 事件报错；`timeline.music` 为 `null` 时 `hit/energy` 恒为 0、`moment` 为 `undefined`、`span` 为空数组。
- `validate_scenes_html` 短片分支：逐镜头、**不含 `global.js`** 渲染；音乐平移 0.2 秒；镜头自己的关键帧全部没变为错误，部分没变为警告。
- 总时长校验：`beatsheet` 总时长在 [8, 180] 秒；与 `brief.md` 目标时长偏差超过 15% 警告，超过 40% 错误。
- 新依赖：仅声明 `numpy>=2,<3`（已由 manim 间接安装）；不引入 librosa、scipy、matplotlib。
- 分层：三个新阶段与其他阶段互不 import（independence 契约）；`stages` 可依赖 `engines`、`timeline`、`agent`。
- 测试标记：需要真实 Chromium、ffmpeg、Seatbelt 的测试标 `slow`，不进 `make check`。

## 评审重点

规格隐含、但最容易在实际使用中出问题的五类情况（每条都已在对应任务里加了测试）：

1. **配乐脚本写死秒数或 BPM**：用另一套 BPM（短片）或总长（讲解）重跑，时长或事件名变了就报"脚本似乎写死了时间"（T5）。
2. **脚本异常、超时、缺产物、越界写、沙箱不可用**：错误带 stderr 末尾，`music/` 里的旧产物不被动，越界写被本轮越界检查拦下（T3、T5）。
3. **节拍脚本与配乐、配乐与时间轴不一致**：`beatsheet` 改了而配乐没重渲染，`render.json` 的 `base_hash` 对不上，`finalize_blockers` 点名原因；`events.json` 声明的 BPM 或总长与时间轴不一致被拒（T1、T5、T6）。
4. **画面对 `env.hit` 误用**：对 `sweep` 事件调用 `hit`、事件名拼错，报错里要给出可用名称与用法；无配乐项目调用不抛错（T7）。
5. **短片画面全靠 HUD 或字面时刻"假敏感"**：逐镜头且不含 `global.js` 的平移检查能抓住只靠 `global.js` 响应节拍的镜头；`lt` 与数字字面量比较有警告（T8）。

## 验收标准

- [ ] AC1：`build_timeline` 三种来源（短片、讲解 + 背景乐、无配乐讲解）与错误汇总符合设计 §4.1；`TimelineSources` 读取顶层与 `upstream/`、拒绝缺文件与符号链接越界；`base_hash` 不随事件与能量变化，`hash` 随之变化（验证方式：`tests/timeline/`）
- [ ] AC2：`engines.audio` 的 WAV 读取、`analyze`（对齐率、事件匹配分类、能量曲线映射、波形包络）、分析图、`run_compose` 符合设计 §7.3（验证方式：`tests/engines/test_audio_*.py`；`-m slow` 的沙箱用例）
- [ ] AC3：`concept`、`beatsheet` 阶段与 `check_concept`、`validate_beatsheet` 符合设计 §6.1、§6.2（验证方式：`tests/stages/test_concept_*.py`、`test_beatsheet_*.py`）
- [ ] AC4：`render_music` 与 `music` 阶段符合设计 §7：成功路径写齐五个托管文件、失败路径不动旧产物、重定时校验、沙箱不可用、`finalize_blockers`（验证方式：`tests/stages/test_music_*.py`）
- [ ] AC5：运行时 `env.hit/span/energy/moment` 语义符合设计 §5（验证方式：`tests/engines/test_html_browser.py` 的 slow 用例，纯逻辑部分用表驱动）
- [ ] AC6：`animation_html` 在短片与讲解 + 背景乐下按形态生成时间轴；`validate_scenes_html`、`render_preview_html` 的短片分支符合设计 §6.3（验证方式：`tests/stages/test_animation_html_*.py`）
- [ ] AC7：`GET /api/video-kinds` 里短片与"讲解 + 合成背景乐"可用，创建项目成功；MV 与"导入音乐"仍不可用；设置页阶段列表含三个新阶段；旧项目与 Manim 路径的现有测试全部通过（验证方式：`tests/api/test_video_kinds.py`、`test_projects.py`、前端单测、`make check`）
- [ ] AC8：fake 运行时分别跑通短片和"讲解 + 合成背景乐"的整条流水线，每个阶段产物齐全且能定稿；联调测试从真实 `render_music` 产物走到画面校验（验证方式：`tests/api/test_synth_music_flow.py`、`-m slow`）
- [ ] AC9：真实模型（`claude-login`）走完一个短片小项目（2 段 × 2 小节），`validate_beatsheet`、`render_music`、`validate_scenes_html` 最终无错误（验证方式：`make smoke SMOKE_ARGS="-k motion_reel_claude_login"`，证据写到 `data/evidence/synth-music/smoke/`）
- [ ] AC10：L4：在内置浏览器里创建"动态图形短片"项目，阶段导航为 概念 → 节拍脚本 → 配乐 → 动画，通用画布能看到各阶段产物（验证方式：控制者截图）
- [ ] AC11：`ARCHITECTURE.md`、`QUALITY.md`、`docs/runbooks/verification.md`、`docs/references/` 已同步；`make check` 全绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->
<!-- 依赖：T1、T2 互相独立；T3 依赖 T2；T4 依赖 T1；T5 依赖 T1、T3；T6 依赖 T1、T5；T7 独立；T8 依赖 T1、T7；T9 依赖 T4、T6、T8；T10 依赖 T9 -->

### T1：时间轴三层与按形态读取（待开始）

- **目标**：`studio.timeline` 支持网格、节拍脚本点、配乐三层，并能按项目形态从工作区或 `upstream/` 读取（设计 §4）。
- **涉及文件**：`backend/src/studio/timeline/{build,load,__init__}.py`；调用方适配：`backend/src/studio/worker_html.py`、`backend/src/studio/api/html_preview.py`、`backend/src/studio/stages/animation_html/prepare.py`（及 `common.py` 中的 `load_timeline`，若用到）；`backend/tests/timeline/{test_build,test_load}.py`（含新用例）。
- **接口与要点**：
  - 输入数据类：`GridInput(bpm, offset)`、`SectionInput(id, label, bars)`、`MomentInput(section_id, at, visual_action)`、`MusicInput(file, events, energy_hop, energy_values)`；`TimelineLayers` 的 `grid/moments/music` 改用这些类型，另增 `sections: list[SectionInput] | None`（短片用）；`narration` 在短片里为空列表。
  - `build_timeline`：短片——段落按 `bars × 4 × 60 / bpm` 首尾相接，`grid.beats` 每 `60/bpm` 一个时刻、覆盖整片再多一拍，`downbeats` 每 4 拍，`moments[].t = section.start + parse_at(at, bpm)`；讲解 + 背景乐——沿用叙事段落，`grid` 由声明的 `bpm/offset` 覆盖整片；`music` 层把 `MusicInput` 变成 `Music`（`file` 固定 `music/music.wav`，`energy={hop, values}`）。校验（汇总成 `TimelineError`）：BPM 在 [40, 240]；`bars` 为正整数；`at` 可解析且落在本段内；事件名非空、`kind` 为 `onset`/`sweep`、起止在 [0, duration] 且 `start ≤ end`；声明的 `duration` 与时间轴相差不超过 0.05 秒；短片声明的 BPM 与节拍脚本相差不超过 0.01。
  - `load.py`：`TimelineSources(root, prefix="", narration, music_source, with_music=True)`；`load_workspace_timeline(sources) -> LoadedTimeline(timeline, hash, base_hash, narrative, timing, beatsheet)`。短片读 `beatsheet/beatsheet.json`；有旁白读叙事与 timing；`music_source=synth` 且 `with_music` 时读 `music/events.json` 与 `music/analysis.json`（只取 `energy`、`hop`）。`base_hash` = 去掉 `music` 层后的时间轴哈希。符号链接越界、缺文件、JSON 损坏都汇总成 `TimelineError`。
  - 调用方：用 `kind_from_settings(project.settings)` 得到 `narration`、`music_source`，构造 `TimelineSources`；无配乐的讲解结果与改动前逐字节一致。
- **测试**：表驱动覆盖三种来源的段落起止、网格拍数与强拍、`moments.t`（用 `parse_at` 的结果交叉核对）、`music` 层映射；每类错误一条用例，且一次报出多条；`TimelineSources` 读顶层与 `upstream/`、`with_music=False`、缺文件、符号链接越界；`base_hash` 在改事件或能量时不变而 `hash` 改变，改网格或段落时两者都变；回归：现有的旁白时间轴测试与 `worker_html`/`html_preview`/`animation_html` 相关测试不改一行也通过。
- **完成标准**：`tests/timeline` 与受影响的现有测试通过；`lint-imports` 通过。
- **验证命令**：`cd backend && uv run pytest tests/timeline tests/test_worker_html.py tests/api/test_html_preview.py tests/stages/test_animation_html_stage.py -v && uv run lint-imports`

### T2：`engines.audio` ——WAV、分析、能量曲线（待开始）

- **目标**：纯能力层的音频读取与分析，不含运行器和画图。
- **涉及文件**：`backend/pyproject.toml`（`numpy>=2,<3`；import-linter 契约）、`backend/src/studio/engines/audio/{__init__,wav,analysis}.py`、`backend/tests/engines/{test_audio_wav,test_audio_analysis}.py`、`backend/tests/fixtures/audio/`（测试音频的生成函数，不入库二进制）。
- **接口与要点**：
  - `wav.read_wav(path) -> Samples(data: ndarray[float64, (n,) 或 (n,2)], sample_rate)`：只用标准库和 NumPy，支持 PCM 16/24/32 位与 float32、单双声道；采样率限 22050–96000，时长上限和文件大小上限为常量（实现里定数值并写进决策记录）；不支持的格式、超限、损坏都抛 `AudioError`（中文）。
  - `analysis.analyze(samples, timeline, events, *, retime=False) -> MusicReport`，字段：时长；峰值 dBFS、削波样本数；整体 RMS；各段 RMS 与频谱重心；起音点列表；起音与 1/16 网格对齐率；`EventMatch`（分名统计，只含"可检测"的 `onset` 事件）与 `undetectable` 事件列表（起点早于 50 ms，或被紧邻更强起音掩蔽）；`energy(hop, values)`；`waveform`（1000 点峰值包络）；`warnings: list[str]`（削波、过轻、整体 RMS 越界——短片目标 -16 到 -9 dBFS、背景乐 -30 到 -20 dBFS、`energy` 为 `low→peak` 的相邻段 RMS 没有上升）。起音检测沿用小试：对数压缩谱流量，窗 2048、步长 512，局部峰值阈值 0.12。
  - 事件校验函数 `validate_events(doc, timeline) -> list[str]`：对象形状（`bpm`、`duration`、`events`）、名称、`kind`、起止、声明值与时间轴一致性（讲解不查 `bpm`）。
  - 数值常量（窗、阈值、目标 RMS）集中在模块顶部，便于调参。
- **测试**：用 NumPy 现场合成的测试音频：已知 BPM 的底鼓串（对齐率、匹配率接近 100%）、整体偏移 80 ms 的底鼓串（对齐率下降）、含 t=0 事件与扫频事件（分类进 `undetectable`/不计分母）、全静音、削波音频、24 位与 float32 WAV、单双声道；能量映射端点（-40 dBFS→0，-6 dBFS→1）；波形包络长度；`read_wav` 各种非法输入。
- **完成标准**：测试通过；契约生效（`engines.audio` 故意 import `studio.agent` 时 `lint-imports` 失败，实现后通过）。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_audio_wav.py tests/engines/test_audio_analysis.py -v && uv run lint-imports`

### T3：`engines.audio` ——分析图与脚本运行器（待开始）

- **目标**：Pillow 自绘分析图；在沙箱里运行合成脚本并回收产物。
- **涉及文件**：`backend/src/studio/engines/audio/{picture,runner}.py`；`backend/tests/engines/{test_audio_picture,test_audio_runner}.py`。
- **接口与要点**：
  - `picture.render_analysis_png(report, timeline, events, samples) -> bytes`：三行（波形、对数频率谱图、起音强度），叠加段落边界、小节线与拍线、事件标记（按名称分色并带图例）；谱图用自带颜色表（NumPy 查表）；图宽约 1800、高约 1000；字体用 Pillow 默认字体，文字只用 ASCII，避免缺字。
  - `runner.run_compose(script, timeline_path, out_dir, *, timeout, wrap_command) -> RunResult(wav_path, events_path, stdout, elapsed)`：在 `out_dir` 下执行 `python script`（解释器为当前 `sys.executable`），`cwd=out_dir`，环境变量 `STUDIO_TIMELINE`、`STUDIO_OUT_WAV`、`STUDIO_OUT_EVENTS` 指向 `out_dir`；`wrap_command: Callable[[list[str], dict[str, str]], list[str]]` 由调用方提供；超时终止整个进程组；非零退出、缺产物抛 `ComposeError`，消息带 stderr 末尾 30 行；`stdin` 显式指定为 DEVNULL（仓库守卫测试要求）；设 `RLIMIT_CPU`（`preexec_fn`）。
- **测试**：
  - 图：返回合法 PNG、尺寸固定、事件很多或为空时不崩、`report` 全静音时不崩。
  - 运行器（用假的 `wrap_command` 恒等包装，不依赖沙箱）：成功路径产出两个文件；脚本抛异常、不写产物、写了 WAV 没写 events、超时（用 `time.sleep` 脚本）、输出 stdout；超时后进程组被杀、没有残留子进程。
  - `slow`（真实 Seatbelt，仅 macOS）：用 `shell_sandbox.seatbelt_profile` 包装的真实运行——脚本能写 `out_dir`、不能读仓库根与数据目录、不能联网、写 `out_dir` 之外的路径被拒（Seatbelt 层面）。
- **完成标准**：非 `slow` 测试通过；`slow` 在本机通过。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_audio_picture.py tests/engines/test_audio_runner.py -v`；`uv run pytest -m slow tests/engines/test_audio_runner.py -v`

### T4：`concept` 与 `beatsheet` 阶段（待开始）

- **目标**：两个不写代码的阶段及其校验工具、提示词，注册进应用（设计 §6.1、§6.2）。
- **涉及文件**：`backend/src/studio/stages/concept/{__init__,check_concept}.py` 与 `prompt.md`；`backend/src/studio/stages/beatsheet/{__init__,schema,validate_beatsheet}.py` 与 `prompt.md`；`backend/src/studio/main.py`（注册）；`backend/pyproject.toml`（independence 与 `stages.pipeline` 契约）；`backend/tests/stages/{test_concept_stage,test_concept_check,test_beatsheet_stage,test_beatsheet_validate,test_beatsheet_prompt}.py`；`frontend/src/composables/stageTitles.ts` 已含标题，无需改。
- **接口与要点**：
  - `ConceptStage`：`name="concept"`，`allow_web=True`，`reads()=[]`，可写 `concept/brief.md`，`artifact_dirs()=["concept"]`，工具 `web_search`、`fetch_url`、`check_concept`；`finalize_blockers` 重新运行检查；`status_summary` 为"已有 X/7 个章节"。
  - `check_concept(workdir)`：纯函数加工具包装；固定章节 `主题`、`目标时长`（要能解析出数字秒数，如 `30 秒`）、`情绪与能量走向`、`视觉母题`、`参考与灵感`、`段落草图`、`风险点`；缺章节、章节为空、目标时长不可解析为错误。
  - `BeatsheetStage`：`reads()=[concept, music]`，可写 `beatsheet/beatsheet.json`，工具 `validate_beatsheet`、`suggest_upstream_change`；`finalize_blockers` 重新运行校验。
  - `schema.py`（pydantic）：`bpm`、`sections[{id, label, bars, intent, energy, moments[{at, visual_action}]}]`；`validate_beatsheet` 检查项和级别严格按设计 §6.2 与全局约束（id 沿用 `_ID_PATTERN`、段落数 1–12、BPM [60, 200]、`bars` 正整数、`at` 用 `parse_at` 解析且落在本段内并按时间顺序、总时长 [8, 180] 秒、与目标时长偏差 15%/40%）；目标时长从上游 `brief.md` 读取（`upstream/concept/brief.md`），读不到时跳过该项并给警告。
  - 提示词：`concept` 引导提炼主题、情绪走向、视觉母题和段落草图并写出目标时长；`beatsheet` 讲清 BPM 与小节记法（`at` 用"小节.拍"，相对本段，从 1 开始）、`energy` 取值、一小节对应的时长、每段 1–4 个 moment、"画面要做什么"的写法、时长怎么算（总小节数 × 4 × 60 / BPM）。
  - 注册后 `concept`、`beatsheet` 已在注册表里，但 `music` 还没有，所以短片仍因缺 `music` 而不可选，不会出现半成品入口。
- **测试**：`check_concept` 与 `validate_beatsheet` 表驱动（每类错误与警告各一条，含边界值）；阶段定义的可写范围、`reads`、`artifact_dirs`、`finalize_blockers`；提示词包含关键契约词；`upstream_of` 在短片流水线里 `beatsheet` 的上游为 `[concept]`；`GET /api/video-kinds` 里短片仍不可用。
- **完成标准**：测试通过；契约生效。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_concept_stage.py tests/stages/test_concept_check.py tests/stages/test_beatsheet_stage.py tests/stages/test_beatsheet_validate.py tests/stages/test_beatsheet_prompt.py tests/api/test_video_kinds.py -v && uv run lint-imports`

### T5：`render_music` 工具核心（待开始）

- **目标**：运行脚本、校验、重定时校验、写回产物的完整流程，作为纯函数核心加工具包装（设计 §7.4）；核心将在 3B 被 `POST /music/render` 复用。
- **涉及文件**：`backend/src/studio/stages/music/{render,tool}.py`；`backend/tests/stages/test_music_render.py`、`test_music_tool.py`。
- **接口与要点**：
  - `render.render_music_core(workdir, sources, *, wrap_command, timeout=120) -> RenderOutcome(ok, errors, report, png, retime_note)`：
    1. 用 `TimelineSources(with_music=False)` 构造时间轴并写临时 JSON；
    2. `run_compose` 到 `.cache/tmp/music-run-<随机>/`；
    3. `read_wav` + 读 `events.json` → `validate_events` + `analyze`；格式类错误直接失败；
    4. 重定时：短片把 BPM 改成 0.8 倍并按新总长重建时间轴、讲解把各镜头时长乘 1.25，再运行并校验；通过条件——音频时长与新时间轴相差不超过 0.05 秒、事件名集合不变、短片起音对齐率不低于原来的一半；失败写"脚本似乎写死了时间"并带具体差异；重定时运行的产物丢弃；
    5. 全部通过后，原子地把 `music.wav`、`events.json` 移入 `music/`，写 `analysis.json`（`hop/energy/duration/sample_rate/waveform/metrics/wav_hash`）、`analysis.png`、`render.json`（`script_hash/base_hash/wav_hash/bpm/duration/rendered_at`）；
    6. 任何一步失败，`music/` 保持原样；临时目录总是清理。
  - 工具 `render_music`（无参数）：沙箱包装 = `shell_sandbox` 的 Seatbelt（`deny_read` 与 Shell 一致，取仓库根与 `data_dir`；沙箱不可用返回"当前平台没有沙箱，不能运行合成脚本"）；成功后用 `ctx.record_tool_write` 登记五个托管文件；返回一张 PNG 和文本：时长、峰值与削波、整体与分段 RMS 与重心、起音与网格对齐率、事件匹配率分项、检测不到的事件、警告，末尾固定一句"音色、和声、混响量与声像无法由指标判断，需要用户试听"。
  - 工具层不依赖 `agent` 内部以外的东西；`render_music_core` 不 import `agent`（包装函数由调用方传入），方便 3B 的 api 复用。
- **测试**：用小而快的参考脚本夹具（纯 NumPy，~1 秒）与恒等 `wrap_command`：成功路径五个托管文件齐全、内容与哈希一致；写死秒数的脚本（对任何时间轴都输出 15 秒的固定 BPM 曲）被重定时拒绝、`music/` 旧产物不变；脚本抛错、超时、缺 events、events 声明的 `bpm`/`duration` 与时间轴不一致、WAV 时长不对——各自失败且旧产物不变；讲解形态的重定时；沙箱不可用时工具返回错误；工具文本包含固定的试听提示且附一张 PNG。
- **完成标准**：测试通过；一次 `slow` 用例用真实 Seatbelt 包装跑通参考脚本。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_music_render.py tests/stages/test_music_tool.py -v`；`uv run pytest -m slow tests/stages/test_music_tool.py -v`

### T6：`music` 阶段定义、`prepare_turn`、提示词、注册（待开始）

- **目标**：阶段本身（设计 §7.1、§7.5），注册后两种形态可创建。
- **涉及文件**：`backend/src/studio/stages/music/{__init__,prepare}.py`、`prompt.md`、`exemplar/audio-techniques.py`；`backend/src/studio/main.py`；`backend/pyproject.toml`（契约）；`backend/tests/stages/{test_music_stage,test_music_prompt}.py`；`backend/tests/api/test_video_kinds.py`、`test_projects.py`（新用例）。
- **接口与要点**：
  - `MusicStage`：`name="music"`，`allow_web=False`，`reads()=[concept, narrative, beatsheet]`，可写 `music/compose.py`，工具托管 `music/{music.wav,events.json,analysis.json,analysis.png,render.json}`，工具 `render_music`、`suggest_upstream_change`，`artifact_dirs()=["music"]`。
  - `prepare_turn`：用 `TimelineSources(prefix="upstream/", with_music=False)` 写 `upstream/timeline.json`（失败时删旧文件、写 `timeline.error.txt`，沿用 `animation_html` 的做法）；复制金样本到 `upstream/exemplar/audio-techniques.py`（由 `docs/temp/reel/audio.py` 整理成约 200 行的技法节选：底鼓、拍手、镲片、贝斯、扫频、冲击、混响卷积；去掉与成品耦合的部分；作为包资源入库）。
  - `finalize_blockers`：`render.json` 缺失；`compose.py` 哈希与 `script_hash` 不一致；当前 `base_hash`（实时从 `upstream/` 或顶层重算，与调用时机一致）与 `render.json` 的不一致；`music.wav` 缺失或哈希不符；每条中文点名原因与处理办法。
  - `status_summary`：未渲染 / 已渲染（时长、BPM、事件数）。
  - 提示词按设计 §7.5：输入、脚本契约、"你听不到声音"、指标只证明对齐、短片与讲解两种编排、事件命名建议、工作流（先节奏骨架、渲染看图、再加铺底与效果）、收尾必须汇报"哪些东西无法验证"。
  - 注册 `MusicStage`；`unavailable_reason` 自动放开短片与"讲解 + 合成背景乐"，MV 与"导入音乐"仍因缺阶段（`analyze_music` 等未实现，它们的流水线里没有额外未注册阶段，所以需要显式规则）——**先确认现有 `unavailable_reason` 对 `music_source=import` 的判断**，若只靠"阶段是否注册"则 MV 与"导入音乐"会被误放开，此时加一条显式的"导入音乐尚未实现"规则并写进决策记录。
- **测试**：阶段协议值；`prepare_turn` 对短片与讲解各生成正确的 `timeline.json`（不含 `music` 层）、不可用时写错误文件；`finalize_blockers` 每类原因一条；提示词包含关键契约词；`GET /api/video-kinds`：短片与讲解 + 合成背景乐可用，MV 与导入音乐不可用；`POST /projects` 能创建短片项目，阶段行为 `concept, beatsheet, music, animation_html`；设置页阶段列表（前端单测）含三个新阶段名。
- **完成标准**：测试通过；`make check-fast` 通过。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_music_stage.py tests/stages/test_music_prompt.py tests/api/test_video_kinds.py tests/api/test_projects.py -v && uv run lint-imports`；`cd frontend && pnpm test -- settings`

### T7：HTML 运行时 `env.hit/span/energy/moment` 与 `include_global`（待开始）

- **目标**：把运行时占位换成实现，`assemble` 支持不含 `global.js` 的组装（设计 §5、§6.3）。
- **涉及文件**：`backend/src/studio/engines/render/html/{runtime.js,assemble.py}`；`backend/tests/engines/test_html_assemble.py`、`test_html_browser.py`（新用例）。
- **接口与要点**：
  - `runtime.js`：按设计 §5 的表实现；`hit` 在名字不存在、`kind=sweep` 时抛带可用名称与用法的错误；`span(name)` 返回 `[{start, end}]` 局部秒；`energy(lt?)` 线性插值并截断端点；`moment(i)` 返回 `{at, t, action}`，越界 `RangeError`；`timeline.music` 为 `null` 时保持原行为（0、`undefined`、`[]`）。
  - `assemble(workdir, timeline, *, preview=False, inline=False, include_global=True)`；`include_global=False` 时页面不含 `global.js`；`page_hash` 与之无关。
- **测试**：`assemble` 的 `include_global` 两种取值；`slow`（真实 Chromium，极小固定场景）：`hit` 在事件起点为 1、之后按 `exp(-Δt/0.18)` 衰减、起点之前为 0；对 `sweep` 与未知名称的报错文本；`span`；`energy` 插值与端点；`moment`；无配乐时三者的原行为；`bt/bar` 仍取全局第 n 拍与第 n 小节的局部秒。
- **完成标准**：非 `slow` 测试通过；`slow` 在本机通过；旧的运行时 slow 用例不改也通过。
- **验证命令**：`cd backend && uv run pytest tests/engines/test_html_assemble.py -v`；`uv run pytest -m slow tests/engines/test_html_browser.py -v`

### T8：`animation_html` 的短片分支（待开始）

- **目标**：按形态生成时间轴；校验与预览工具适配短片；提示词补短片节（设计 §6.3）。
- **涉及文件**：`backend/src/studio/stages/animation_html/{prepare,common,validate_scenes_html,render_preview_html,prompt.md}`；`backend/src/studio/engines/render/html/{probe,static_check}.py`；`backend/tests/stages/test_animation_html_{stage,tools,prompt}.py`、`backend/tests/engines/{test_html_probe,test_html_static_check}.py`。
- **接口与要点**：
  - `prepare_turn`：用 `TimelineSources(prefix="upstream/")`（形态取自 `ToolContext`/阶段调用方能拿到的项目设置——**先确认 `prepare_turn(workdir)` 如何得知项目形态**；若拿不到，则由 `upstream/` 里存在 `beatsheet/` 或 `narrative/` 目录判断，并把这条判断写进决策记录）；短片把 `upstream/beatsheet/beatsheet.json` 的段落意图保留给 agent 读。
  - `probe`：新增 `music_shift_sensitivity(page, timeline, scene_id, *, shift=0.2) -> SensitivityReport` 与短片版 `sample_times`：必选点为镜头起止附近、每个节拍脚本点 +0.04、每个强拍 +0.04、出现次数最少的至多 4 个事件的起点 +0.04，再用均匀采样补到 16 张。
  - `static_check`：新增警告——`lt` 与数字字面量比较（`lt > 3.5`、`3.5 < lt`），提示"时刻必须来自 `env`"；不报错，注释里出现不报。
  - `validate_scenes_html`：形态为短片时，敏感度检查换成逐镜头、`include_global=False` 的音乐平移检查（镜头自己的关键帧全部没变为错误，部分没变为警告并点名）；有旁白的镜头沿用 beat 敏感度；输出文本形状不变（`scene_checks` 照常解析）。
  - `render_preview_html`：短片用新采样；拼图每格标注 `t` 与 `lt`（沿用）；其余不变。
  - 提示词：单份 `prompt.md` 按 `narration` 是否为空分两节；短片节写 `bt/bar/hit/span/energy/moment` 契约表、`hit` 的 0.18 秒衰减、`sweep` 事件用 `span`、"所有时刻只能由 `env` 推出，不许写字面秒数"、"节拍可见性不能全靠 HUD"、冲击前留半拍静默、`global.js` 只做后期不承担节奏。
- **测试**：短片的 `prepare_turn`（含 `music` 层、`narration` 为空）；`validate_scenes_html` 短片分支——正确使用 `hit/bt` 的镜头通过、只有 `global.js` 响应节拍的镜头为错误、部分关键帧没变为警告、`lt > 3.5` 有警告、注释里的不报；`render_preview_html` 短片采样点包含节拍脚本点与强拍；无旁白不触发 beat 敏感度；有旁白项目的现有测试不改一行也通过；提示词包含短片节的关键契约词。
- **完成标准**：测试通过；既有 `animation_html` 测试全部通过。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_animation_html_stage.py tests/stages/test_animation_html_tools.py tests/stages/test_animation_html_prompt.py tests/engines/test_html_probe.py tests/engines/test_html_static_check.py -v`；`uv run pytest -m slow tests/stages/test_animation_html_tools.py -v`

### T9：整流水线集成与联调（待开始）

- **目标**：fake 运行时分别跑通两种形态的整条流水线，并做"真实配乐产物 → 时间轴 → 画面校验"的联调（AC8）。
- **涉及文件**：`backend/tests/api/test_synth_music_flow.py`；`backend/tests/fixtures/synth_music/`（短片的 `brief.md`、`beatsheet.json`、参考合成脚本 `compose_ref.py`、示范镜头脚本；讲解形态复用 `tests/fixtures/animation/` 与 `tests/fixtures/animation_html/` 夹具）。
- **接口与要点**：
  - 流程测试（仿 `test_animation_html_flow.py`）：fake 运行时脚本化每个阶段的一轮——`concept` 写 `brief.md` 并 `check_concept`；`beatsheet` 写并校验；`music` 写 `compose.py` 并调用 `render_music`（真实核心，恒等 `wrap_command` 用于非 slow 版）；`animation_html` 写镜头并校验、预览；每个阶段完成后定稿，下游的 `upstream/` 与 `timeline.json` 正确；讲解 + 背景乐同理（叙事夹具 + 音频静音 wav）。
  - 联调：`slow`——用参考合成脚本跑真实 Seatbelt 的 `render_music`，把产物读回时间轴，驱动 `animation_html.prepare_turn` 与 `validate_scenes_html`（真实 Chromium），断言：`env.hit('kick')` 在 `events.json` 的每个 kick 起点为 1；`env.energy` 与 `analysis.json` 一致；示范镜头通过校验。
  - 失败回流：节拍脚本改动后 `music` 的 `finalize_blockers` 点名"与当前时间轴不一致"；配乐重渲染后 `animation_html` 变旧（现有 stale 机制）。
- **测试**：即上述用例。
- **完成标准**：流程与联调测试通过；全量 `make check` 与 `-m slow` 全部通过。
- **验证命令**：`cd backend && uv run pytest tests/api/test_synth_music_flow.py -v && uv run pytest -m slow tests/api/test_synth_music_flow.py -v`；`make check`

### T10：真实模型冒烟、L4 与收尾（待开始）

- **目标**：用真实模型验证（AC9），完成 L4（AC10），文档同步（AC11）。
- **涉及文件**：`backend/tests/smoke/test_smoke.py`（新用例 `test_motion_reel_claude_login`）、`backend/tests/smoke/support.py`（`build_harness` 注册三个新阶段）、`docs/runbooks/verification.md`、`docs/ARCHITECTURE.md`、`docs/quality/QUALITY.md`、`docs/references/motion-reel-spike.md`（补"3A 落地后的变化"）、`docs/plans/TODO.md`、本计划的验证记录。
- **接口与要点**：
  - 冒烟：短片小项目——`concept` 一轮（给出主题与目标时长 7.5 秒）、`beatsheet` 一轮（2 段 × 2 小节，128 BPM）、`music` 一轮（写脚本、至少调用 `render_music` 一次，成功）、`animation_html` 一轮（2 个镜头，校验通过）；每个阶段定稿后进入下一个；每轮步数上限与 2A 一致，允许至多一次追加轮；断言流程与产物形状、最后一次校验无错误、`render_music` 成功、只写了可写范围内的路径；记录耗时、轮数、费用、警告，不评价观感；证据写到 `data/evidence/synth-music/smoke/`。
  - L4（控制者，隔离实例：api 8010、前端 5174、临时数据目录）：创建"动态图形短片"项目、阶段导航为 概念 → 节拍脚本 → 配乐 → 动画；种子项目里通用画布能看到各阶段产物（`music/analysis.png` 若通用画布不支持图片，则只验证文件树列出，并记入 3B 的画布工作）；"讲解 + 合成背景乐"可创建；MV 与导入音乐仍不可用并显示原因。
  - 文档：ARCHITECTURE 依赖表加入 `engines.audio`、`stages.concept/beatsheet/music`；QUALITY 新增模块行；runbook 加冒烟命令与 L4 步骤；TODO 里把"子项目 3"拆为"3A 已完成、3B 待办"。
- **测试**：冒烟用例本身；再跑 `make check` 与全部 `slow` 测试。
- **完成标准**：AC1–AC11 逐条附证据；`make check` 全绿。
- **验证命令**：`make smoke SMOKE_ARGS="-k motion_reel_claude_login"`；`make check`；`cd backend && uv run pytest -m slow -v`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-05 — 计划写成，开始 T1

## 下一步

- T1：时间轴三层与按形态读取。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-05 — `render_music_core` 不 import `agent`，沙箱包装由调用方传入：3B 的 api 端点复用同一份核心，api 层自己取 Seatbelt。
- 2026-10-05 — T6 需要先确认 `unavailable_reason` 对"导入音乐"的判断；T8 需要先确认 `prepare_turn(workdir)` 如何得知项目形态。两处都可能让计划里的一小步改写，改写写进这里。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 暂无

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 待填
