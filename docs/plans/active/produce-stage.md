# produce-stage：配乐与动画合并阶段

<!-- 本计划实现 docs/design/2026-10-06-produce-stage.md。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 待验收 |
| 里程碑 | 多形态视频后续（子项目 3、4 的重构） |
| 设计依据 | [produce-stage 设计](../../design/2026-10-06-produce-stage.md)；被取代范围见该设计 §10 |
| 分支 | `feat/produce-stage`（从 `feat/session-chat-layout` 末端切出，设计文档提交 `c33a258` 在其上） |
| 批准记录 | 2026-10-06：负责人批准计划，选择本会话内联执行 |
| 执行方式 | 本会话内联（不派子代理），完成后由一个独立评审检查整个分支 |

## 目标

「动态图形短片」和「音乐 MV」的流水线变成 `concept → produce` 两个阶段：模型在 `produce` 里自己决定节拍、镜头划分和对齐方式，配乐与画面联动迭代；同时修掉让配乐阶段整轮失败的 1 MiB 消息缓冲区问题。

## 范围

**包含：**

- 修复 1 MiB 缓冲区问题（T1，可单独合入）。
- 新增 `produce` 阶段（工具、定稿条件、提示词）、`shots.json`、`range.json`；`concept` 增加「硬性要求」与 MV 的上传分析。
- 时间轴对短片、MV 的新读取路径；删除 `beatsheet` 阶段与 MV 的 `sections.json`。
- 校验降级、预览采样、成片前置检查、预览端点、前端画布合并与上传区迁移。
- 文档同步，真实模型冒烟与 L4。

**不包含：**

- 讲解类（Manim / HTML，含合成与导入配乐）的任何行为变化；`Timeline` schema 的字段变更。
- 旧项目数据兼容（调试期，旧项目作废）。
- 音乐 MV 的画面质量（TODO 里单列的 P2）。

## 全局约束

- 设计 §2：模型决定网格、段落、镜头、对齐；系统只给客观事实与最小校验。
- `engines`、`timeline` 保持纯能力层，不 import `agent`、`stages`；import-linter 契约不变。
- 外部 SDK 行为以 `docs/references/` 为准；新发现补进 references，注明日期与来源。
- 不用 `skip`、`xfail`、`# type: ignore`、`noqa` 绕过失败；每个任务结束 `make check` 为绿，至少一个 commit，格式 `<type>(<scope>): <中文说明>`。
- 工作区里不用 git；`data/` 不进 uvicorn reload 监听范围。

## 审查重点

这些是设计隐含、但各任务测试不一定覆盖的输入或状态，每条都在对应任务里有一条测试：

1. **已被毒化的会话**：历史里已经带了一条超 1 MiB 的消息（例如本次现场的会话）后，再发一轮必须能继续，不能再失败（T1）。
2. **`shots.json` 与配乐时长不符**：镜头总长比音频短或长、缺文件、`id` 含非法字符、镜头数为 1，错误信息要点名文件和差值（T2）。
3. **改了配乐没重渲就定稿或出片**：脚本、`wav`、`events.json` 任一与 `render.json` 不一致，定稿和成片都要拒绝并说明要重新 `render_music`（T3、T8）。
4. **MV 的 `range.json` 缺省、越界、起点非零**：缺省用整首歌；起点非零时事件与能量整体平移，预览音频偏移和成片截取一致（T2、T8）。
5. **工具返回过大**：事件上千个、镜头几十个、预览图十几张时，单条工具结果的文本与图片总量都在预算内（T1、T5）。

## 验收标准

- [ ] AC1：`render_music`、`analyze_music` 等带图的工具结果，序列化成 CLI 的一条消息（图在 `message` 与 `toolUseResult` 里各一份）后小于 1 MiB，且 SDK 的 `max_buffer_size` 提高到不会再因这类消息失败；已毒化会话的追加轮能继续。（验证：`backend/tests/stages/test_picture_budget.py`、`backend/tests/agent/test_claude_runtime_options.py`；L4 用现场项目再发一轮）
- [ ] AC2：短片与 MV 的 `pipeline` 都是 `["concept", "produce"]`；`beatsheet` 阶段、`validate_beatsheet`、`validate_sections`、`sections.json` 在代码与测试里已不存在；讲解类流水线与行为不变。（验证：`make check`；`grep` 无残留）
- [ ] AC3：fake 运行时能把短片与 MV 各自从创建项目一路走到定稿并出成片；MV 的 `concept` 阶段能上传歌曲并分析。（验证：新增的流水线测试与 api 流测试）
- [ ] AC4：`produce` 内改配乐后，预览、校验、成片使用的是最新产物；陈旧时给出明确提示。（验证：stale 与前置检查测试）
- [ ] AC5：真实模型冒烟——短片、MV 各一次走完 `concept → produce` 并出成片。（验证：`make smoke` 相应用例，按 smoke-testing-policy 用本地 Claude 登录）
- [ ] AC6：L4——浏览器里创建短片与 MV 项目，验证导航、`concept` 的上传区、`produce` 画布的试听与实时预览，附截图。
- [ ] AC7：`make check` 全绿，文档（ARCHITECTURE、QUALITY、glossary、references、TODO）同步。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：修复 1 MiB 消息缓冲区问题（完成）

- **根因（2026-10-06 实测）**：CLI 把工具结果里的图片在同一条消息里写两份（`message.content[].content[].source.data` 和顶层 `toolUseResult[].source.data`）。`render_music` 的 JPEG 394 KB → base64 525 324 字节，两份加上封装为 1 054 050 字节，超过 SDK 默认的 1 048 576。`common.picture` 现有预算（单张 400 KB、总 600 KB）只按一份算，所以 3A 的修复没有覆盖这个场景。第二个现象：追加轮会带上这条历史消息，所以重试同样失败。
- **目标**：带图工具结果的序列化消息不再逼近上限；SDK 缓冲区留足余量；已毒化的会话能继续。
- **涉及文件**：`backend/src/studio/stages/common/picture.py`、`backend/src/studio/agent/claude_runtime.py`（`ClaudeAgentOptions(max_buffer_size=…)`）、`backend/src/studio/stages/music/tool.py`、`backend/src/studio/stages/music/analyze.py`、`backend/src/studio/stages/animation/render_preview.py`、`backend/src/studio/api/music.py`（共用压缩的调用点）、`docs/references/claude-agent-sdk.md`、`backend/tests/stages/test_picture_budget.py`（新）、`backend/tests/agent/test_claude_runtime_options.py`（新或并入现有）。
- **接口与要点**：
  - 预算改按"每张图在消息里出现两次"计：同一条结果里所有图片的 **base64 总长 ≤ 400 kB**（折合原始字节约 300 kB），`DEFAULT_LIMIT_BYTES` 与 `TOTAL_LIMIT_BYTES` 相应下调；`limit_for(count)` 的语义不变（返回每张的原始字节上限）。把"消息里出现两次"写进模块文档。
  - `max_buffer_size` 设为 **8 MiB**（`config` 里放常量，不加环境变量）：这是兜底，不是放行大图；图片预算仍是第一道。
  - 文本也要有上限：`ToolResult.text` 超过 **60 kB** 时在工具层截断并提示"已截断，按需读文件"（统一放在 `ToolResult` 构造的公共出口，不逐工具改）。
  - 已毒化会话：提高缓冲区后，历史里那条 1.05 MB 的消息可以被读入，追加轮不再失败。不另做会话修复逻辑。
- **测试（先写）**：
  1. 用 `compress_png` 压一张故意做成难压缩的大图，构造与 CLI 同形的"两份"消息，断言序列化长度 < 900 000。
  2. `limit_for(1..6)` 的总和 × 2 × 4/3 < 800 000。
  3. `ClaudeAgentOptions` 构造结果的 `max_buffer_size` 为 8 MiB。
  4. 文本超 60 kB 的工具结果被截断并带提示。
  5. （审查重点 1）用 SDK 的传输层解析函数喂一条 1.05 MB 的行，在新缓冲区下能解析。
- **完成标准**：上述测试通过；`docs/references/claude-agent-sdk.md` 补一节"图片在一条消息里出现两次"，注明 2026-10-06 与证据（会话记录里那条 1 054 050 字节的消息）。
- **验证命令**：`make check`；L4 在 T10 一并做。
- **可单独合入**：这个任务不依赖其他任务，可先合入 `main`。

### T2：时间轴的 `produce` 读取与 `shots.json` 校验（完成）

- **目标**：短片与 MV 在不依赖 `beatsheet.json`、`sections.json` 的情况下读出时间轴；`shots.json` 与 `range.json` 有独立校验。
- **涉及文件**：`backend/src/studio/timeline/load.py`、`timeline/build.py`、`timeline/imported.py`（删除节拍脚本、强拍对齐、`moments`、段落边界校验）、`timeline/shots.py`（新）、`timeline/__init__.py`、`backend/tests/timeline/test_shots.py`（新）、`test_load.py`、`test_import_timeline.py`、`test_sources.py`。
- **接口与要点**：
  - `parse_shots(doc) -> list[TimedSectionInput]` 与 `parse_range(doc, audio_duration) -> tuple[float, float]`，错误汇总成 `TimelineError`。复用 `build_timeline` 现有的 `timed_sections` 路径（MV 已在用），不新增层。
  - `TimelineSources` 新增形态 `"produce"`：`music_source` 为 `synth` 读 `music/events.json`、`analysis.json`（能量）、`animation/shots.json`；为 `import` 读 `analysis.json`、`source.*`、可选 `music/range.json`、`animation/shots.json`。**不读** `beatsheet.json`、`sections.json`。
  - 时长：短片取 `events.json.duration`，并要求与 `shots.json` 最后一个 `end` 在现有 `_DURATION_TOLERANCE`（0.05 秒）内（见决策记录 D1）；MV 取 `range` 长度。
  - MV 的 `music.events`：由 `analysis.json` 的 `beats`、`downbeats` 生成名为 `beat`、`downbeat` 的 `onset` 事件，减去 `range.start`，丢弃区间外的；能量同样按区间截取。`grid`、`moments` 为 `None`/`[]`。
  - `import_hash` 口径保持（时间轴哈希 + 源哈希 + range）。`base_hash` 不再有意义：`LoadedTimeline.base_hash` 保留字段供讲解类使用，`produce` 形态下与 `hash` 相同。
  - `env.bt/bar/moment` 在 `grid is None` 时调用要抛出明确错误并提示 `hit/span/energy`（检查 `engines/render/html/runtime.js` 现状，缺则补）。
- **测试（先写）**：`shots.json` 缺失 / 非法 JSON / 缺字段 / `id` 非法或重复 / 不首尾相接 / 不覆盖整段 / 末端与时长差超容差 / 单镜头合法；`range.json` 缺省 / 越界 / 起点非零时事件与能量平移；`beat`、`downbeat` 事件生成；`timeline_hash` 对 `shots.json` 与 `range` 敏感；`env.bt` 在无网格时报明确错误（审查重点 2、4）。
- **完成标准**：讲解类的时间轴测试不变且通过；`produce` 形态的读取覆盖上述情形。
- **验证命令**：`make check`。

### T3：配乐渲染与导入分析去掉时间轴依赖（完成）

- **目标**：`render_music` 不再需要上游时间轴；`render.json` 不含 `base_hash`；MV 的分析不再依赖 `sections.json`。
- **涉及文件**：`backend/src/studio/stages/music/render.py`、`music/tool.py`、`music/analyze.py`、`engines/audio/runner.py`（去掉 `STUDIO_TIMELINE` 注入，保留给讲解类的可选入参）、`engines/audio/analysis.py`、`engines/audio/song.py`（按需）、对应测试 `test_music_render.py`、`test_music_tool.py`、`test_music_import_tools.py`。
- **接口与要点**：
  - `render_music_core` 的 `timeline`、`base_hash`、`section_energy` 变为可选；`timeline is None` 时：不注入 `STUDIO_TIMELINE`、**不做"换 BPM/总长重跑"检查**（没有时间轴可对照）、`events.json` 的 `bpm` 可选、`render.json` 为 `{script_hash, wav_hash, duration, rendered_at}`。讲解类仍走原路径，行为不变。
  - `analysis`（`MusicReport`）在无网格时：不报"落在 1/16 网格的比例"，改报起音数与能量摘要；`event_matches`（声明事件与实测起音匹配）保留。
  - 事件超过 200 个时，工具文本只列前若干个与统计，完整内容在 `events.json`（配合 T1 的体积预算）。
  - `analyze_music` 不再提示"请手动修正 sections.json"，改为提示可选写 `music/range.json`；导入形态的分析输出保留 `bpm`、`beats`、`downbeats`、`confidence`，作为模型的可选参考。
- **测试（先写）**：无时间轴的渲染成功与失败路径（脚本抛错、缺产物、超时、沙箱不可用都不改动旧产物）；讲解类渲染回归；事件 607 个时文本长度在预算内；`analyze_music` 新提示文案（审查重点 5）。
- **完成标准**：讲解类的音乐测试全部通过；新路径覆盖上述情形。
- **验证命令**：`make check`。

### T4：`produce` 阶段本体（完成）

- **目标**：注册 `produce` 阶段，含写入范围、工具集合、`prepare_turn`、定稿条件、状态摘要与提示词。
- **涉及文件**：`backend/src/studio/stages/produce/__init__.py`、`prepare.py`、`blockers.py`、`prompt.md`、`exemplar/`（复用 `music/exemplar/audio-techniques.py` 与 `animation_html/exemplar/canvas-techniques.js`，由 `prepare_turn` 复制，不复制文件本体）、`backend/tests/stages/test_produce_stage.py`（新）、`test_produce_prompt.py`（新）、`backend/src/studio/main.py`（注册）。
- **接口与要点**：
  - 按设计 §5.1 的表实现 `StageDefinition`：`reads() = ["concept"]`，`artifact_dirs() = ["music", "animation"]`，写入范围与托管文件如设计所列。
  - 形态判断：`music/source.*` 存在为 MV（复用 `stages.common.music_source.find_source`），否则短片。`tools()` 取超集；错误形态返回明确提示。
  - 现有工具按 `ToolSpec.stages` 过滤，所以给 `render_music`、`analyze_music`、`validate_scenes_html`、`render_preview_html`、`suggest_upstream_change` 的 `stages` 集合加上 `"produce"`（它们对 `produce` 的行为差异在 T3、T5 里按工作区内容处理）。
  - `prepare_turn`：只复制金样本；**不再写 `upstream/timeline.json`**（工具即时构建，见设计 §6）。上游 `concept` 缺失时写 `upstream/timeline.error.txt` 的做法取消。
  - `finalize_blockers` 与 `status_summary` 按设计 §5.4、§5.5；`finalize` 的闸口沿用动画阶段的做法（只能在"成片"之后定稿，见 `ProjectWorkbenchPage.vue` 注释），`produce` 加入 `stageActions` 的同一类。
  - 提示词 `prompt.md`：目标与手段，不规定顺序；涵盖配乐技法、`env` 契约（`hit/span/energy`、不可用的 `bt/bar/moment`）、`shots.json` 与 `range.json` 的格式、"对齐由你负责，用预览自查"、用 `suggest_upstream_change` 反馈创意问题、体积预算的提醒（事件和能量按需读文件）。
- **测试（先写）**：写入范围放行与拒绝；`finalize_blockers` 逐项（审查重点 3）；`status_summary` 两种形态；错误形态下的工具提示；提示词里关键约定的存在性断言（沿用现有 prompt 测试风格）。
- **完成标准**：阶段可被注册表取得；T2、T3 的产物读写在阶段层测试里连通。
- **验证命令**：`make check`。

### T5：校验与预览的适配（完成）

- **目标**：`validate_scenes_html`、`render_preview_html` 在 `produce` 形态下按设计 §7 工作。
- **涉及文件**：`backend/src/studio/stages/animation_html/validate_scenes_html.py`、`render_preview_html.py`、`common.py`（时间轴即时构建的读取入口，取代读 `upstream/timeline.json`）、`engines/render/html/static_check.py`（如需）、对应测试 `test_animation_html_tools.py`、`test_animation_preview.py`、`test_animation_html_stage.py`。
- **接口与要点**：
  - 工具先调 T2 的读取入口取时间轴；失败时返回明确的"时间轴不可用：…"。`shots.json` 校验先行，镜头文件缺失逐一点名。
  - 音乐敏感度检查（整体平移 0.2 秒）的平移对象改为 `music.events` 与 `energy`；结果级别**降为警告**，文案点名镜头。有旁白的节拍敏感度检查不动。
  - 字面量时间静态警告保留。
  - 预览采样必选点：镜头起止附近、能量峰值、出现次数最少的几类事件的起点，再均匀补满 16 张；总图片预算走 T1 的新预算（审查重点 5）。
  - 讲解类（有旁白）路径与测试不变。
- **测试（先写）**：短片与 MV 各一组夹具上的警告与采样断言；预览 16 张图的总序列化长度在预算内；讲解类回归。
- **完成标准**：同一份 `validate_scenes_html` 对三类形态各自正确。
- **验证命令**：`make check`。

### T6：`concept` 的「硬性要求」与 MV 的上传分析（完成）

- **目标**：`brief.md` 增加「硬性要求」；MV 在 `concept` 阶段就能上传歌曲、分析并据此写创意。
- **涉及文件**：`backend/src/studio/stages/concept/__init__.py`、`check_concept.py`、`prompt.md`、`stages/music/analyze.py`（`ANALYZE_MUSIC_TOOL.stages` 加 `"concept"`）、`api/music_import.py`（上传端点放行 `concept` 阶段）、`stages/common/target_duration.py`（如依赖 `beatsheet`）、`tests/stages/test_concept_stage.py`、`test_concept_check.py`、`tests/api/test_music_upload.py`。
- **接口与要点**：
  - `concept` 的 `artifact_dirs` 加 `music`；写入范围保持 `concept/brief.md` 与笔记，托管文件加 `music/source.*`、`analysis.json`、`analysis.png`。`concept` 的 `prepare_turn` 对短片无变化。
  - `check_concept` 多检查「硬性要求」章节存在（内容不评价），目标时长仍必须可解析。
  - `concept` 的提示词在 MV 有 `source.*` 时引导先读分析再写创意；短片不提上传。
  - 上传端点的项目与阶段校验：允许在 `concept`、`produce` 两个阶段上传（MV 项目），讲解类项目仍拒绝。
- **测试（先写）**：缺「硬性要求」时报错；MV 项目在 `concept` 阶段上传成功、短片项目上传 409；`analyze_music` 在 `concept` 可用，短片里调用返回明确提示；`concept` 定稿后上传的歌曲被 `produce` 看到。
- **完成标准**：MV 在 `concept` 阶段能走完"上传 → 分析 → 写 brief → 定稿"。
- **验证命令**：`make check`。

### T7：流水线、预设、API 与旧路径清理（完成）

- **目标**：把形态与阶段表改成新流水线，删除 `beatsheet`，清理 `music`、`animation_html` 里只为短片与 MV 服务的分支。
- **涉及文件**：`backend/src/studio/stages/pipeline.py`、`api/video_kinds.py`、`api/schemas.py`（预设文案）、`db/repo/settings.py`、`main.py`（注册 `produce`，去掉 `beatsheet`）、删除 `stages/beatsheet/`、`stages/music/validate_sections.py`、`timeline/build.py` 里的 `layers_from_beatsheet` 与 `GridInput`/`MomentInput` 中仅短片用到的路径（讲解 + 合成配乐仍用 `GridInput`，保留）、`stages/music/__init__.py` 与 `prepare.py`、`sources.py`（`infer_sources` 的"有 beatsheet 即短片"判断删除，只服务讲解）、`stages/animation_html/prepare.py` 与 `__init__.py`（删除短片、MV 分支，`reads` 改为 `["narrative", "music"]`）、相关测试（删除 `test_beatsheet_*.py`、`test_validate_sections.py`、`test_music_video_pipeline.py` 中被取代的部分，改写 `test_pipeline.py`、`test_video_kinds.py`、`test_projects.py`、`test_settings.py`）。
- **接口与要点**：
  - `build_pipeline`：`motion_reel` 与 `music_video` 都返回 `["concept", "produce"]`。预设描述改文案（"先定创意与要求，再由模型一并完成配乐与动画"）。
  - `unavailable_reason`、`STAGE_TITLES`（后端与前端各一份）加入 `produce: 配乐与动画`，去掉 `beatsheet`。
  - 阶段配置键（`settingsView.ts` 的阶段模型覆盖列表）同步。
  - 删除后用 `grep -rn "beatsheet\|sections.json\|validate_sections"` 在 `backend/ frontend/ docs/` 里确认只剩历史文档与设计文档的引用。
- **测试（先写）**：流水线与可用性断言；创建项目写入的 `pipeline` 设置；`stage_flow` 的上游与 stale 链（`concept` → `produce`）；import-linter 契约通过。
- **完成标准**：AC2 的 grep 条件满足；讲解类项目创建与阶段行为不变。
- **验证命令**：`make check`。

### T8：api 与成片 worker（完成）

- **目标**：预览、音频、渲染端点和成片前置检查适配 `produce`。
- **涉及文件**：`backend/src/studio/api/html_preview.py`、`api/music.py`、`api/music_import_meta.py`、`worker_html.py`、`worker.py`（按需）、`engines/render/mix.py`（按需）、测试 `test_html_preview.py`、`test_music.py`、`test_music_import_meta.py`、`test_synth_music_flow.py`、`test_html_render_flow.py`、`tests/test_worker_html_music.py`。
- **接口与要点**：
  - `html_preview._preview_music` 与 `worker_html._music_source` 去掉对 `base_hash` 的比对，只核对 `wav_hash` 与 `render.json`；MV 预览的音频偏移取 `range.start`（缺省 0），不再读 `sections.json`。
  - `music/meta` 端点按形态返回：短片返回事件、能量、BPM（可选）与 `render.json` 状态；MV 返回分析摘要与 `range`，去掉段落字段（`MusicSectionOut` 删除或改为镜头来源）。
  - `POST /music/render` 对 `produce` 阶段放行并去掉时间轴前置（沿用 T3 的无时间轴渲染）。
  - 成片：缺 `shots.json` 或镜头文件时错误点名文件；`final.json` 里 MV 的 `music.range` 字段保留。
  - 前置检查的失败文案统一指向 `produce` 阶段（"需要在『配乐与动画』阶段重新渲染"）。
- **测试（先写）**：改配乐后预览与成片拒绝使用旧音频（审查重点 3）；MV 的 `range` 起点非零时预览偏移与成片截取一致（审查重点 4）；`shots.json` 缺失的错误文案；讲解类成片回归。
- **完成标准**：fake 运行时的短片与 MV 整条流程（创建 → `concept` 定稿 → `produce` 渲染 → 成片 → 定稿）通过。
- **验证命令**：`make check`。

### T9：前端画布与导航（完成）

- **目标**：`produce` 的画布与 MV 的上传区迁移；阶段标题、设置页、类型契约同步。
- **涉及文件**：`frontend/src/pages/ProjectWorkbenchPage.vue`（阶段分发）、`features/canvas/animation/HtmlAnimationCanvas.vue`（增加配乐标签）、`features/canvas/music/`（复用 `MusicPlayer`、`WaveformView`、`EventTable`、`EnergyView`、`RenderReport`、`SourceUploader`、`AnalysisSummary`；拆出可共用的子组件，不复制）、`features/canvas/generic/`（`concept` 画布加 MV 上传区）、`features/canvas/stageActions.ts`、`composables/stageTitles.ts`、`features/settings/settingsView.ts`、`types/api.ts`、`test/videoKindsFixture.ts`、`features/ideas/CreateProjectDialog.vue` 与对应 spec。
- **接口与要点**：
  - `stage === 'produce'`：用 `HtmlAnimationCanvas` 作主体（预览、成片），标签行加「脚本 / 事件 / 分析」（短片）或「分析」（MV）；保存、冲突状态机沿用 `composables/conflictState.ts`，写入的阶段键为 `produce`。
  - 成片定稿的闸口与 `animation_html` 同类（`stageActions`）。
  - `concept` 阶段在 MV 项目里显示上传区与分析摘要；短片项目不显示。判断依据用项目设置里的 `video_kind`，不用工作区文件。
  - 删除 `ImportMusicCanvas`、`MusicCanvas` 中仅服务旧阶段的入口，保留被讲解类使用的部分（`music` 阶段仍存在）。
- **测试（先写）**：vitest 覆盖阶段标题与导航、`produce` 画布标签与播放来源切换、`concept` 上传区的显示条件、`stageActions` 的闸口、`CreateProjectDialog` 的流水线描述、设置页阶段列表。
- **完成标准**：`pnpm test`、`pnpm lint`、`pnpm typecheck`（以 `make check` 为准）通过。
- **验证命令**：`make check`。

### T10：文档、冒烟与 L4（待开始）

- **目标**：文档同步；真实模型冒烟；浏览器验证。
- **涉及文件**：`docs/ARCHITECTURE.md`、`docs/glossary.md`、`docs/quality/QUALITY.md`、`docs/quality/tech-debt.md`、`docs/references/import-music-mv.md`、`docs/references/claude-agent-sdk.md`（T1 已补）、`docs/plans/TODO.md`、`backend/tests/smoke/`（新增短片、MV 各一个用例，沿用 `support.py`）、本计划的「验证记录」。
- **要点**：
  - 文档里去掉对 `beatsheet`、`sections.json` 的现行描述，指向 produce 设计；旧设计文档不改。
  - 冒烟：本地 Claude 登录，短片与 MV 各跑一次到出片；记录用量与时长、是否出现过缓冲区问题。
  - L4（控制者在内置浏览器里做）：创建两种项目；MV 在 `concept` 上传并分析；`produce` 里试听、预览、出片、定稿；用现场的毒化会话（项目 `f67bd800…`，会话 `eed19681…`）再发一轮，确认不再失败。
  - TODO：把本计划移到「已完成」；追加"讲解类是否也取消阶段拆分"的 P2。
- **完成标准**：AC5、AC6、AC7。
- **验证命令**：`make check`；`make smoke`（指定用例）。

## 进度

- 2026-10-06 — T9 — 完成：`produce` 画布复用 `HtmlAnimationCanvas`（新增 `stage` 属性与 `music` 槽，多一个「配乐」标签；页面按歌曲/合成形态填入 `ImportMusicCanvas`（不上传、compact）或 `MusicCanvas`（`stage="produce"`））；MV 的 `concept` 阶段在文件画布上方显示上传区与分析摘要；阶段标题（创意与要求、配乐与动画）、设置页阶段表、`stageActions`、类型（去掉 `sections_check`）、分析摘要与预览文案同步；新增/改写 vitest。`make check` 全绿。页面级分发没有单元测试（`ProjectWorkbenchPage` 本来就没有 spec），留给 T10 的 L4。
- 2026-10-06 — T7 + T8 — 完成（合并实施）：流水线 `concept → produce`；删除 `beatsheet` 阶段、`validate_sections`、`notation.py`、`layers_from_beatsheet`/`layers_from_import`、`SectionInput`/`MomentInput`；`music`、`animation_html` 只服务讲解；`api/music*`、`html_preview`、`worker_html`、`animation_stage`（出片阶段解析为 `produce`）、`scene_checks`、`reopen` 适配；`music/meta` 去掉 `sections_check`；短片 `render.json` 无 `base_hash`；测试与夹具全部迁到 `produce` 形态（新增 `test_produce_pipeline.py` 等），冒烟用例改为 `concept → produce`。`make check` 全绿，`-m slow` 77 个全过（真实 Chromium、ffmpeg、沙箱）。
- 2026-10-06 — T6 — 完成：`SECTIONS` 加「硬性要求」（八章）；`concept` 增加 `analyze_music` 工具、`music/source.*`/`analysis.*` 托管、`artifact_dirs = [concept, music]`；`concept` 提示词改写（两种项目、硬性要求、MV 先上传再分析）；`produce` 提示词补「简报写明基于歌曲但没有 source 时请用户先上传」。上传端点本来就不绑定阶段（按项目形态放行），无需改动，`test_music_upload.py` 在 `concept` 阶段上传的用例已覆盖。`make check` 全绿（夹具 `fixtures/synth_music/seed.py` 的简报补了「硬性要求」；教训：提交前必须看 `make check` 的结果，上一个提交 `e857a2f` 当时有 4 个测试失败，由紧随其后的提交修好）。
- 2026-10-06 — T5 — 完成：`validate_scenes_html`/`render_preview_html` 的 `stages` 加 `produce`；`helpers.load_timeline` 在 `produce` 阶段按 `shots.json` 与 `music/` 即时构建时间轴；音乐平移检查在 `produce` 下降为警告；镜头数 > 40 警告；`probe.is_reel` 不再要求网格、关键时刻加入能量峰值并只取罕见事件名（≤ 12 次）。`make check` 全绿。
- 2026-10-06 — T4 — 完成：`stages/produce/`（`__init__.py`、`prepare.py`、`blockers.py`、`prompt.md`）、金样本移到 `common/{score,scenes}/exemplar`、`main.py` 注册、import-linter 契约加入 `produce`；`make check` 全绿。`validate_scenes_html`/`render_preview_html` 在 `produce` 下的行为留给 T5（其 `stages` 集合在 T5 补）。
- 2026-10-06 — T4 前置 — 完成：共用工具搬到 `stages/common/score`、`common/scenes`（D7），`make check` 全绿。
- 2026-10-06 — T3 — 完成：`render_music_core(timeline=None)` 自由模式（脚本无时间轴输入、不重定时、`render.json` 无 `base_hash`、`bpm` 可选；`run_compose` 的 `timeline_path` 可空；`validate_events(bpm_required=…)`）；`render_music` 按 `ctx.stage == "produce"` 分流，`analyze_music` 在 `concept`/`produce` 给出 `range.json` 的提示；`compose_free.py` 夹具。
- 2026-10-06 — T2 — 完成：`timeline/shots.py`（`parse_shots`、`parse_range`）、`TimelineSources.produce`、短片与 MV 的读取（MV 事件由 `beats`/`downbeats` 生成 `beat`/`downbeat`）；`runtime.js` 的 `bt/bar/moment` 报错加了替代写法；`make check` 全绿。
- 2026-10-06 — T1 — 完成：图片预算按两份折算（总 base64 ≤ 400 kB）、`invoke_tool` 兜底（文本 ≤ 60 000 字节、超预算图片整组丢弃）、`max_buffer_size` 8 MiB、references 补记；`make check` 全绿。

## 下一步

- T10 已完成：文档、浏览器 L4、两条真实模型冒烟都已记入「验证记录」。剩余：1）整分支独立评审（`code-review`）并修完；2）`make check`；3）把状态改为待验收，交负责人验收（含 MV 成片试听，文件在 `data/evidence/import-music/smoke/music-video-final.mp4`）。

## 决策记录

- D14（2026-10-06）：features 之间不能互相 import（ESLint 规则），所以 `HtmlAnimationCanvas` 不直接引用 `music/` 下的组件，而是开一个 `music` 槽，由 `ProjectWorkbenchPage` 按歌曲/合成形态填进去。阶段显示名「创意」改为「创意与要求」（前后端各一份 `STAGE_TITLES`）。
- D11（2026-10-06）：T7 与 T8 合并实施——旧路径（`beatsheet`、`sections.json`）还被 api/worker/预览读着，必须先让它们走 `produce` 再删，分开提交会有一段红灯。`music` 阶段瘦身为只服务「讲解 + 背景乐」，`render_music_core` 去掉 `section_energy`；`engines.audio.analyze` 的 `section_energy` 形参保留（引擎层纯能力，其测试覆盖了趋势警告）。
- D12（2026-10-06）：`api/projects.py` 的 `reopen` 原来只对 `animation` 撤销「已完成」标记；改为对项目的出片阶段（`animation`/`animation_html`/`produce`）都撤销——顺带修了 `animation_html` 的同类遗漏。
- D13（2026-10-06）：`validate_scenes_html` 的音乐平移检查彻底降为警告（不再保留 `strict` 分支）——旧的错误级别只服务过去的短片/MV，现在它们都是 `produce`。
- D9（2026-10-06）：「硬性要求」放在「目标时长」之后、「情绪与能量走向」之前（第 3 章）；MV 项目靠 `music/source.*` 是否存在区分形态，阶段拿不到项目设置，所以 `concept`/`produce` 的提示词都写了「简报说基于歌曲但没有上传时请用户先上传」。
- D10（2026-10-06）：`concept` 的 `artifact_dirs` 含 `music`，意味着重新定稿 `concept` 时若 `music/` 下内容与 `produce` 所基于的快照不同（换歌，或 `produce` 之后又写了配乐产物）就会把 `produce` 标为 stale；换歌触发 stale 是想要的，「`concept` 内容没变也 stale」是已知的小误报（`stage_flow` 只按目录前缀比较），记入 tech-debt 即可。
- D8（2026-10-06）：预览采样的「最少见的几类事件」限定为整条时间轴里出现次数 ≤ 12 的名字——否则 MV 的 `beat`/`downbeat`（几十到上百次）会占满 16 张预览。设计 §7 写的「出现次数最少的几类事件」按此落实。
- D7（2026-10-06）：T4 发现 import-linter 契约「各阶段之间互不 import（规则 3）」禁止 `produce` 直接复用 `music`、`animation_html` 里的工具。处理：把共用的工具实现纯搬迁（行为不变）到 `stages/common/`——`music/{render,tool,analyze,sources}.py` → `common/score/`，`animation_html/{common,validate_scenes_html,render_preview_html}.py` → `common/scenes/`（`common.py` 改名 `helpers.py`，并带走 `TIMELINE_PATH`/`ERROR_PATH`）；两个旧阶段改为从 `common` 导入。没有改任何公共接口，也没有放宽契约。
- D6（2026-10-06）：自由模式下没有时间轴，长度以音频本身为准，`events.json` 声明的 `duration` 只做与实际音频一致的校验（沿用 0.05 秒容差）；不再对总长设上下限（WAV 读取已有大小与时长上限）。
- D4（2026-10-06）：T2 只**新增** `produce` 读取路径，不删 `imported.py`、`layers_from_beatsheet` 等旧路径——旧阶段在 T7 之前仍在用，删除放在 T7，保证每个任务结束时 `make check` 为绿。
- D5（2026-10-06）：相邻镜头的缝隙 ≤ 1 ms 时由 `parse_shots` 自动贴合（设计 §5.3 的 1 ms 容差落在解析处），其余首尾相接判断仍用 `build_timeline` 的 1e-6 精度；末端与音频时长的差值用 0.05 秒（D1）。
- D1（草稿，2026-10-06）：`shots.json` 的末端与音频时长的容差沿用 `timeline.build` 现有的 `_DURATION_TOLERANCE`（0.05 秒），而不是设计 §5.3 写的 1 ms——避免模型为一个毫秒级差值反复改镜头；相邻镜头首尾相接仍按 1 ms。若负责人要严格按设计，T2 里改一个常量即可。
- D2（草稿，2026-10-06）：`max_buffer_size` 取 8 MiB、文本工具结果上限 60 kB；两个数字来自 1 MiB 现场数据与现有预算，实测后可调。
- D3（草稿，2026-10-06）：MV 的 `music.events` 由分析的 `beats`/`downbeats` 生成 `beat`/`downbeat` 两类 `onset` 事件，让模型有 `hit('beat')` 可用；设计 §6 只写"来自分析结果"，这里落到具体。

## 意外与发现

- 2026-10-06：1 MiB 问题的真正原因不是图片太大，而是 CLI 在同一条消息里写两份图片（`message` 与 `toolUseResult`）；3A 的"单张 400 KB"预算按一份算，所以没挡住。证据：项目 `f67bd800…` 的会话记录里两条 1 054 050 / 1 054 379 字节的行。

## 阻塞

- 无

## 验证记录

- L4（2026-10-06，内置浏览器，隔离实例：api 8010 / 前端 5174 / 临时数据目录 / 假运行时 / 独立 worker，`scratchpad/seed_l4.py` 种子）：
  - 短片（`produce` active）：阶段导航「创意与要求✓ / 配乐与动画」；标签 镜头（2）/ 实时预览 / 配乐 / 成片；「配乐」标签有播放器、波形上的镜头标记（BUILD/DROP）、指标与分析图，「脚本」标签点「渲染」在真实 Seatbelt 沙箱里渲染成功（无重定时提示）；实时预览能播（0:00 / 0:16，镜头按钮）；「成片」渲染完成（0:16）并「成片定稿」，阶段导航变为「配乐与动画✓」、出现「重新打开」。
  - MV（有歌，`produce` active）：「配乐」标签是播放器 + 能量曲线（叠加 intro/verse/chorus 镜头与拍线）+ 分析摘要，没有上传区。
  - MV（`concept` active，无歌）：文件画布上方是「上传一首歌」上传区；用 API 上传后刷新，显示播放器、「还没有能量曲线：让 agent 调用 analyze_music」、「更换歌曲」，文件树出现 `music/source.wav`。
  - 控制台无报错。
  - 发现并记下的环境事项：隔离实例要单独起 `studio.worker`，否则成片任务一直「排队中」（不是缺陷）。
- 1 MiB 问题的现场复测（项目 `f67bd800…` 的毒化会话）**未做**：那是负责人的真实数据，且旧流水线项目已作废；用 SDK 的单行解析测试（`TestMessageBuffer`）与冒烟记录的最长行代替，见上。
- 真实模型冒烟（2026-10-06，Claude 本地登录，详见 `docs/references/produce-stage.md`）：
  - 短片：通过，26 分 19 秒；`produce` 会话最长一行 565 778 字节（< 1 MiB）。
  - MV（海阔天空，324.8 秒）：通过，14 分 13 秒；`produce` 42 步、6 个镜头，成片 324.83 秒；听感待负责人试听。第一次运行失败是冒烟用例的读取顺序错误（已修）。
  - 意外：MV 的 `produce` 会话里模型用内置 `Read` 读了 `music/analysis.png`，得到 1 065 448 字节的一行（> 1 MiB），靠 8 MiB 缓冲才通过。
