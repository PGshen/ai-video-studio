# M3：叙事阶段（narrative.json/timing.json、TTS 与 beat 对齐）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | M3 |
| 设计依据 | [架构设计 §5.2、§5.4、§10](../../design/2026-09-26-architecture.md) |
| 分支 | `m3-narrative` |
| 批准记录 | 2026-09-29：负责人批准计划，执行方式为当前会话内联执行（不派发 subagent），T13 需要真实付费 Volcengine key 一并获得同意 |

## 目标

用户能在一个项目里（选题简报用手工准备的 fixture 顶替，因为 M4 未实现）打开叙事阶段：narrative agent 编写 `narrative/narrative.json`（镜头与 beats），用 `validate_narrative` 静态校验产物结构，用 `synthesize_tts` 对指定或全部镜头生成配音并把逐字时间戳对齐到每个 beat，产出 `narrative/timing.json`；叙事画布能看到镜头卡片、按 beat 分段的音频播放条，校验通过且配音最新、对齐覆盖率达标后用户可以"定稿"；动画阶段（M2 已实现）沿用同一套产物读取叙事定稿，重新定稿时下游前言按镜头 id 给出新增/删除/旁白变化/beat 变化的摘要，而不是文件级 diff。

## 范围

**包含：**

- `engines.tts`：Volcengine TTS 引擎迁移（`TTSEngine` 协议、`VolcengineTTSEngine`、音色映射表、按环境变量读取 API key 的工厂函数）。
- `engines.tts.beat_aligner`：beat 对齐算法迁移，适配新 schema（按稳定 `id` 而不是 `scene_index`；不再有 `fallback_weight`，插值时统一按等权重处理）；`normalize_alignment_text` 一并留在这里，供 `stages.narrative` 复用。
- `stages.narrative`：产物 schema（`scenes[].{id,narration,visual_intent,beats[]}`）、`validate_narrative` 工具、`synthesize_tts(scene_ids)` 工具、完整系统提示词、`suggest_upstream_change` 接入。
- `agent.preamble`：`_upstream_changes` 对"叙事→动画"这一条边按镜头 id 给出新增/删除/旁白变化/beat 变化摘要（TD-6、design §5.4），其余上下游边仍是文件级摘要。
- 手工选题简报 fixture：绕过未实现的 M4，提供 `topic/brief.md` 样例，供开发和测试解锁叙事阶段（对称于 M2 T4 的"手工叙事 fixture"）。
- 前端 `features/canvas/narrative/`：镜头卡片列表（旁白、beats、校验标记）、带 beat 刻度的音频播放条、原始 JSON 标签页、"配音是否最新/对齐覆盖率"状态展示；接入 `ProjectWorkbenchPage.vue`。
- 文档：`.env.example`、`docs/runbooks/verification.md`（新增一条 TTS 冒烟用例）、`docs/references/`（Volcengine TTS 已验证行为，如有必要）。

**不包含：**

- M4 选题打磨阶段本身（brainstorm、search、`check_brief`）——本计划只消费手工 fixture。
- 音色选择/试听的设置页 UI（M5「设置页、TTS 音色」范围）；本计划只从 `project.settings` 读一个固定字段，没有选择器界面。
- 对齐覆盖率阈值的可配置 UI；先写死一个常量，执行中如需调整记入决策记录。
- `suggest_upstream_change` 的完整用户体验（对话卡片高亮、阶段导航角标、"去处理"跳转预填）——留给 M5，本计划只是把已有工具接入 `narrative` 阶段的 `tools()`。
- "选题→叙事"边的按内容摘要——design §5.4 只要求"叙事→动画"按镜头 id，选题简报没有"镜头"概念，这条边继续用文件级 diff。
- 多 TTS 引擎/供应商切换——只接 Volcengine，符合设计 §1"已确认前提"表里"渲染引擎第一版只实现 manim"同等的简化原则。

## 验收标准

- [ ] AC1：`VolcengineTTSEngine.synthesize` 在 mock HTTP 层下返回音频字节、时长、逐字时间戳；重试与不可重试错误的判定符合旧行为；`resolve_speaker` 对未知别名/引擎报错（验证：`pytest backend/tests/engines/test_tts_engine.py`）
- [ ] AC2：`beat_aligner.align_scene_beats` 对给定 narration/beats/word_timestamps，输出的 `speech_start_seconds`/`speech_end_seconds` 单调、`alignment_coverage` 计算正确；找不到时间戳的 beat 走插值路径且 `alignment_status="interpolated"`（验证：`pytest backend/tests/engines/test_beat_aligner.py`）
- [ ] AC3：`stages.narrative.schema.validate_and_normalize` 对合法/非法 `narrative.json` 给出正确的错误列表；`cue_text` 拼接必须覆盖 narration（标点/空白归一化后）的校验生效；`transition` 非法值报错（验证：`pytest backend/tests/stages/test_narrative_schema.py`）
- [ ] AC4：`validate_narrative` 工具在 fixture 项目上，对合法产物返回"校验通过"，对故意破坏的产物（缺字段/cue_text 不覆盖 narration/非法 transition）返回 `is_error=True` 且点名具体镜头（验证：`pytest backend/tests/stages/test_narrative_validate.py`）
- [ ] AC5：`synthesize_tts` 工具（mock TTS 引擎，不发真实网络请求）对指定 `scene_ids` 或全部镜头生成 `narrative/audio/<id>.mp3`、更新 `narrative/timing.json`，字段形状与 M2 fixture（`backend/tests/fixtures/animation/timing.json`）一致；只重新配音部分镜头时，其余镜头的 timing 条目原样保留（验证：`pytest backend/tests/stages/test_narrative_synthesize.py`）
- [ ] AC6：`FakeRuntime` 端到端一轮：narrative agent 写 `narrative.json` → 调 `validate_narrative` → 调 `synthesize_tts` → 定稿；animation 阶段从 `upstream/narrative/` 物化的内容里能读到同样 schema 的产物并跑通 `validate_scenes`（验证：`pytest backend/tests/api/test_narrative_flow.py`）
- [ ] AC7：`agent.preamble._upstream_changes` 对"叙事→动画"边输出按镜头 id 的新增/删除/旁白变化/beat 变化摘要（不是文件级 diff）；"选题→叙事"边仍是文件级摘要（验证：`pytest backend/tests/agent/test_preamble.py`）
- [ ] AC8：前端叙事画布能显示镜头卡片（旁白/beats/校验标记）、按 beat 分段的音频播放条、原始 JSON 标签页；"配音是否最新/对齐覆盖率"状态能正确反映 `timing.json` 与当前 `narrative.json` 是否一致（验证：`make dev` 手动走查 + `pytest frontend`；截图见「验证记录」）
- [ ] AC9：`make check` 全绿
- [ ] AC10：真实 Volcengine API key 下，`synthesize_tts` 完整跑一次合成 + 对齐，产出可播放音频与合理的对齐覆盖率（验证：`make smoke SMOKE_ARGS="-k volcengine_tts"`；需要真实付费 key，属于计划已预先说明的费用，符合 SOP §6 第 7 条的例外记录）

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：`engines.tts` 协议与 Volcengine 引擎迁移（完成）

- **目标**：`backend/src/studio/engines/tts/` 下有可用的 `TTSEngine` 协议和 `VolcengineTTSEngine` 实现，API key 按固定环境变量名读取（不进 `Settings`，与 `model_profiles.api_key_env` 同一原则：真实 key 不落进配置字段）。
- **涉及文件**：
  - 新建 `backend/src/studio/engines/tts/__init__.py`（导出 `TTSEngine`、`TTSRequest`、`TTSResult`、`WordTimestamp`、`VolcengineTTSEngine`、`build_tts_engine`）。
  - 新建 `backend/src/studio/engines/tts/base.py`：迁移 `../ai-video/backend/app/engines/tts/base.py` 的 `TTSRequest`/`WordTimestamp`/`TTSResult`/`TTSEngine` Protocol，字段和签名保持不变。
  - 新建 `backend/src/studio/engines/tts/voice_map.py`：迁移 `../ai-video/backend/app/engines/tts/voice_map.py` 的 `VOICE_MAP_BY_ENGINE`/`resolve_speaker`（不改内容）。
  - 新建 `backend/src/studio/engines/tts/volcengine.py`：迁移 `../ai-video/backend/app/engines/tts/volcengine.py` 的 `VolcengineTTSEngine`（流式解析、重试判定、`_parse_mp3_duration`），只改 import 路径。
  - 新建 `backend/src/studio/engines/tts/factory.py`：**不迁移**旧版 `factory.py`（它依赖已废弃的 `TTSEngineConfig`/`TTSVoice` 表）。新写 `build_tts_engine(*, voice: str, speed: float) -> VolcengineTTSEngine`：从 `os.environ["VOLCENGINE_TTS_API_KEY"]` 读 key（缺失时抛 `RuntimeError`，消息说明去 `backend/.env` 配置），固定 `resource_id="seed-tts-2.0"`、`engine="doubao_2.0"`（决策：先写死单一引擎版本，不做可配置，需要时再加）。
  - `backend/tests/engines/test_tts_engine.py`（新建）：用 `respx` 或手写的 `httpx.MockTransport` 挡住网络（`pyproject.toml` 加 `respx` 测试依赖）。
- **接口与要点**：
  - `TTSRequest.speed` 语义不变（1.0 为正常语速，`speech_rate = round((speed-1.0)*100)`）。
  - 保留原有重试逻辑（`_RETRYABLE_HTTP_STATUS_CODES`、`_NON_RETRYABLE_API_ERROR_MARKERS`），不做行为改动。
  - `.env.example` 补一行注释说明 `VOLCENGINE_TTS_API_KEY`（不带 `STUDIO_` 前缀，和 `ANTHROPIC_API_KEY` 等模型 key 放在同一节）。
  - `ARCHITECTURE.md` 补 `engines.tts` 的 import-linter 契约行（复用已有的"engines 只依赖 config"`forbidden` 契约，`source_modules` 加 `studio.engines.tts` 或确认现有契约按 `studio.engines` 前缀已经覆盖子包，二选一记入决策记录）。
- **测试**：`synthesize` 成功路径（mock 返回音频块 + 时间戳，断言 `TTSResult.success`、`duration_seconds`、`word_timestamps` 内容）；HTTP 5xx 和 429 触发重试且最终耗尽重试次数后返回失败；API 返回"invalid speaker"这类不可重试错误时不重试；`resolve_speaker` 对未知别名/引擎抛 `ValueError`；`build_tts_engine` 缺 key 时抛 `RuntimeError`。
- **完成标准**：`pytest backend/tests/engines/test_tts_engine.py` 通过；无真实网络请求。
- **验证命令**：`make check`

### T2：`engines.tts.beat_aligner` 迁移（适配新 schema）（完成）

- **目标**：`align_scene_beats` 能对新 schema 的镜头（`narration`/`beats[].cue_text`/`word_timestamps`）做字符级对齐，输出每个 beat 的 `speech_start_seconds`/`speech_end_seconds`/`alignment_status` 和整体 `alignment_coverage`。
- **涉及文件**：新建 `backend/src/studio/engines/tts/beat_aligner.py`（迁移 `../ai-video/backend/app/services/beat_aligner.py`）、新建 `backend/src/studio/engines/tts/text_normalize.py`（迁移 `../ai-video/backend/app/services/narrative_validator.py` 里的 `normalize_alignment_text` 及其标点映射表——只搬这一个函数，不搬整个旧 validator，供本模块和 T3 的 `stages.narrative.schema` 共用；`stages` 依赖 `engines` 是允许的方向，见 ARCHITECTURE §2 依赖表）、`backend/tests/engines/test_beat_aligner.py`（新建）。
- **接口与要点**：
  - `align_scene_beats(scene: dict) -> dict` 签名和字段名基本不变；**去掉 `fallback_weight`**：`_interpolate_missing_beats` 里原本读 `beats[i].get("fallback_weight", 1.0)` 的地方改成固定 `1.0`（新 schema 没有这个字段，等权重插值是本计划的简化决定，效果是未对齐上的连续 beat 平均分摊间隙时长）。
  - `ANIMATION_PREROLL_SECONDS`/`ANIMATION_POSTROLL_SECONDS` 及 `animation_start_seconds`/`animation_end_seconds` 保留在函数输出里（可能供未来动画阶段用到更细的入场/退场时机），但 T5 的 `synthesize_tts` 写 `timing.json` 时只取 `speech_start_seconds`/`speech_end_seconds`（不加 pre/post-roll），因为 M2 已有的 `render_preview` 消费的是"发言起止时间"这个更朴素的语义,且要和 `backend/tests/fixtures/animation/timing.json` 里已有的 `beats[].{start_seconds,end_seconds}` 取值方式（紧邻发言边界，无留白）保持一致。
  - `scene.get("scene_index")` 相关代码全部删除（不再需要，日志/报错信息改用调用方传入的 `scene_id` 拼进 `ValueError` 消息，签名加一个可选的 `scene_id: str | None = None` 参数用于报错文案）。
  - `normalize_alignment_text` 的标点映射表原样保留。
- **测试**：narration 被 beats 的 `cue_text` 完整覆盖时，正常对齐路径产出单调递增的 `speech_start/end`；`word_timestamps` 为空（TTS 没返回时间戳）时全部 beat 走插值，覆盖率为 0；部分覆盖时插值只发生在缺口内；`duration_seconds` 缺失时返回 `alignment_status="failed"` 且覆盖率 0（沿用旧行为）；cue_text 拼接和 narration 不匹配时抛 `ValueError`。
- **完成标准**：`pytest backend/tests/engines/test_beat_aligner.py` 通过。
- **验证命令**：`make check`

### T3：`stages.narrative.schema`——产物 schema 与校验规则（完成）

- **目标**：`stages/narrative/schema.py` 定义新 narrative 产物的 pydantic 模型和一个可复用的校验函数，供 T4 的 `validate_narrative` 工具和 T5 的 `synthesize_tts` 工具共用。
- **涉及文件**：新建 `backend/src/studio/stages/narrative/schema.py`、`backend/tests/stages/test_narrative_schema.py`（新建）。
- **接口与要点**：
  - `Beat(BaseModel)`：`cue_text: str`、`visual_action: str`、`emphasis: str`、`transition: Literal["continue","transform","reveal","replace","exit"]`（design §5.2 枚举）。
  - `Scene(BaseModel)`：`id: str`、`narration: str`、`visual_intent: str`、`beats: list[Beat]`。
  - `Narrative(BaseModel)`：`scenes: list[Scene]`。
  - `class NarrativeValidationError(ValueError)`：`errors: list[str]`（沿用旧项目的错误聚合风格，一次性报出所有问题而不是遇到第一个就停）。
  - `validate_and_normalize(raw: dict) -> Narrative`：
    - `scenes` 非空；每个 `scene.id` 非空且在整份文档里唯一；`narration`/`visual_intent`/`beats` 非空；每个 `beat.cue_text`/`visual_action`/`emphasis` 非空。
    - 用 T2 的 `text_normalize.normalize_alignment_text` 把 `narration` 和所有 `beats[].cue_text` 拼接后的结果分别归一化，两者必须相等（否则报"镜头 {id} 的 beats 未完整覆盖 narration"）。
    - `transition` 非法值：pydantic 校验失败的 `ValidationError` 转成人类可读的错误字符串收进 `errors`（不直接透传 pydantic 的英文错误）。
    - 全部通过后返回 `Narrative` 实例；有任何错误则抛 `NarrativeValidationError(errors)`，不返回部分结果（调用方决定怎么呈现）。
- **测试**：合法文档通过；`scenes` 为空、`id` 重复、`cue_text` 拼接少一段/多一段、`transition` 非法值、`beats` 为空数组，各自产生预期的错误信息（用子串断言，不要求逐字匹配）。
- **完成标准**：`pytest backend/tests/stages/test_narrative_schema.py` 通过。
- **验证命令**：`make check`

### T4：手工选题简报 fixture 与开发种子脚本（完成）

- **目标**：在没有 M4 selection/brainstorm agent 的情况下，能创建一个"选题已定稿"的项目，用于本计划其余任务（T5/T6/T9）的测试和 `make dev` 手动走查。参照 M2 决策记录 D6 的教训，本任务提前到消费它的任务之前完成。
- **涉及文件**：新建 `backend/tests/fixtures/narrative/brief.md`、新建 `backend/tests/fixtures/narrative/seed.py`、`backend/tests/conftest.py` 或 `backend/tests/stages/conftest.py`（加一个 `narrative_project` fixture，参照 M2 T4 的 `animation_project` fixture 放置位置）。
- **接口与要点**：
  - `brief.md`：符合设计 §5.1 的章节结构（核心问题；钩子与反直觉点；目标观众与前置知识；关键事实；叙事角度与结构草图；可视化机会；风险点），内容可以简短，只要章节齐全（因为 `check_brief` 是 M4 范围，这里不需要真的通过它）。
  - `seed.py` 提供 `seed_narrative_project(engine, blobs, registry, *, data_dir) -> project_id`：建项目 → 写 `topic/brief.md`（走 `workspace.files`）→ `stage_flow.finalize(engine, blobs, registry, project_id, "topic")`，让 `narrative` 阶段从 `locked` 变 `active`。
- **测试**：`seed_narrative_project` 之后 `get_stage(engine, project_id, "narrative").status == "active"`；`upstream/topic/` 下能读到 `brief.md`（走 `workspace.upstream` 的物化逻辑，和 M2 T4 验证 `upstream/narrative/` 的方式一致）。
- **完成标准**：`pytest` 里依赖这个 fixture 的用例（T5/T6/T9 的测试）都能拿到预期的项目状态。
- **验证命令**：`make check`

### T5：`stages.narrative`——`validate_narrative` 工具（完成）

- **目标**：narrative agent 能调用 `validate_narrative`，读取工作区 `narrative/narrative.json`，用 T3 的 schema 做结构校验，失败时报出具体镜头 id 和原因。
- **涉及文件**：新建 `backend/src/studio/stages/narrative/validate_narrative.py`、`backend/src/studio/stages/narrative/__init__.py`（`tools()` 补上这个 `ToolSpec`）、`backend/tests/stages/test_narrative_validate.py`（新建）。
- **接口与要点**：
  - `ToolSpec`：无入参（空 pydantic model，风格同 `ValidateScenesArgs`），`stages={"narrative"}`。
  - `handler`：从 `ctx.workdir` 读 `narrative/narrative.json`（文件不存在时直接报错"还没有写 narrative.json"，不进 schema 校验），`json.loads` 失败时报错"JSON 格式不合法"（附异常信息），成功解析后交给 `schema.validate_and_normalize`；捕获 `NarrativeValidationError`，把 `errors` 拼成多行文本返回 `ToolResult(is_error=True)`；全部通过时返回"全部 N 个镜头校验通过"。
- **测试**：使用 T4 的 fixture 项目起点，直接往工作区写 `narrative/narrative.json`（合法/含各类错误的版本），断言工具返回内容；文件缺失、JSON 语法错误两条路径单独测。
- **完成标准**：`pytest backend/tests/stages/test_narrative_validate.py` 通过。
- **验证命令**：`make check`

### T6：`stages.narrative`——`synthesize_tts` 工具（完成）

- **目标**：narrative agent 能调用 `synthesize_tts(scene_ids)`，对指定镜头（或全部，`scene_ids=None`）用 T1 的引擎合成配音、用 T2 的对齐算法算出每个 beat 的起止时间，写 `narrative/audio/<id>.mp3` 和 `narrative/timing.json`。
- **涉及文件**：新建 `backend/src/studio/stages/narrative/synthesize_tts.py`、`backend/src/studio/stages/narrative/__init__.py`（`tools()` 补上）、`backend/tests/stages/test_narrative_synthesize.py`（新建）。
- **接口与要点**：
  - `SynthesizeTtsArgs(BaseModel)`：`scene_ids: list[str] | None = None`。
  - `handler(ctx: ToolContext, args)`：
    1. 读 `narrative/narrative.json`（工作区自己的产物，不是 `upstream/`），用 T3 的 `validate_and_normalize` 校验；校验失败直接返回错误（不合法的 narrative 不配音）。
    2. `args.scene_ids` 为 `None` 时取全部 `scene.id`；否则校验每个给定 id 都存在，不存在的直接报错点名。
    3. 用 `db.repo.projects.get_project(ctx.engine, ctx.project_id)` 读 `project.settings`，取 `voice = settings.get("voice", "zizi")`、`speed = settings.get("speech_rate", 1.0)`（决策：默认音色/语速写死这两个值，`project.settings` 目前没有 schema 约束，M3 不新增校验，等 M5 设置页落地时再收紧）。
    4. 对每个目标镜头：`engine.synthesize(TTSRequest(text=scene.narration, voice=voice, speed=speed))`；失败时收集错误，继续处理其余镜头，最后统一报告（不因一个镜头失败中断整个工具调用）。
    5. 成功的镜头：把 `TTSResult.word_timestamps`（`WordTimestamp(word, start_time, end_time)`）转成 `beat_aligner` 需要的 `list[dict]`（`{"word":..., "start_time":..., "end_time":...}`），拼出 `{"duration_seconds": result.duration_seconds, "narration": scene.narration, "beats":[{"cue_text": b.cue_text} for b in scene.beats], "word_timestamps": [...]}`，调用 `align_scene_beats`。
    6. 写音频：`files.write_bytes(ctx.workdir, f"narrative/audio/{scene_id}.mp3", result.audio_bytes)`（工具托管路径，写完后 `ctx.record_tool_write(relpath, sha256)`，`sha256` 用 `hashlib.sha256(audio_bytes).hexdigest()`）。
    7. 更新 `narrative/timing.json`：先读现有文件（不存在则视为 `{"scenes": []}`），按 `id` 替换/追加本次处理的镜头条目，其余镜头原样保留；每个条目字段：`id`、`audio_path`（`f"narrative/audio/{id}.mp3"`）、`audio_hash`（`f"sha256:{sha256}"`，和 M2 fixture 的 `audio_hash` 前缀格式一致）、`duration_seconds`、`beats`（`[{"start_seconds": b["speech_start_seconds"], "end_seconds": b["speech_end_seconds"]} for b in aligned["beats"]]`，**不用**带 pre/post-roll 的 `animation_start/end_seconds`，理由见 T2）、`word_timestamps`（`[{"word": w["word"], "start_seconds": w["start_time"], "end_seconds": w["end_time"]} for w in ...]`，注意字段名从 `start_time`/`end_time` 换成 `start_seconds`/`end_seconds` 以匹配 M2 fixture 的既有命名）、`alignment_coverage`（`aligned["alignment_coverage"]`）。写完后同样 `ctx.record_tool_write("narrative/timing.json", sha256)`。
    8. 返回 `ToolResult`：文本摘要每个镜头的时长、覆盖率；有镜头合成失败时 `is_error=True` 并点名。
  - `_WRITE_SCOPE`（`stages/narrative/__init__.py` 里已有）不用改：`narrative/timing.json` 已经在 `tool_managed`，`narrative/audio/**` 需要新增到 `tool_managed`（目前只有 `narrative/timing.json` 一项，这是本任务对 `_WRITE_SCOPE` 的唯一改动）。
- **测试**：用一个假的 `TTSEngine`（测试替身，不经 T1 的 HTTP 层）注入（`synthesize_tts.py` 的 `build_tts_engine` 调用点做成可替换的，例如模块级 `_ENGINE_FACTORY` 变量或者 handler 接受一个可选的引擎参数，测试里直接调用内部函数而不是走 `ToolSpec.handler` 的默认工厂——具体哪种方式在实现时按代码整洁度选,记入决策记录）：全部镜头合成成功 → `timing.json` 结构和字段名与 M2 fixture 比对一致；只传部分 `scene_ids` → 未指定的镜头 `timing.json` 条目不变；某镜头 `TTSEngine.synthesize` 返回失败 → 工具报错点名，其余镜头仍然成功写入；`narrative.json` 本身不合法 → 直接拒绝，不发起任何合成请求。
- **完成标准**：`pytest backend/tests/stages/test_narrative_synthesize.py` 通过。
- **验证命令**：`make check`

### T7：`stages.narrative`——阶段定义完善（tools 接入 + 完整提示词）（完成）

- **目标**：`NarrativeStage.tools()` 返回 T5/T6 的两个工具加上 `suggest_upstream_change`；`prompt.md` 从占位扩展为完整版（叙事阶段的写作要求、beat 拆分原则、`transition` 语义说明、三个工具的使用时机），参照 `stages/animation/prompt.md` 的详实程度。
- **涉及文件**：`backend/src/studio/stages/narrative/__init__.py`（改 `_TOOLS`，做法同 `stages/animation/__init__.py` 的模块级常量列表）、`backend/src/studio/stages/narrative/prompt.md`（改写）、`backend/tests/stages/test_narrative_prompt.py`（新建，或并入 T5/T6 的测试文件——按现有习惯，`test_animation_validate.py` 里没有单独测提示词内容，这里可以只做一个轻量的"提示词包含关键词"断言，避免专门起一个文件；决定权留给实现时）。
- **接口与要点**：
  - `_TOOLS: list[ToolSpec] = [VALIDATE_NARRATIVE_TOOL, SYNTHESIZE_TTS_TOOL, SUGGEST_UPSTREAM_CHANGE_TOOL]`，`SUGGEST_UPSTREAM_CHANGE_TOOL` 从 `stages.common` 导入（`stages/common/suggest_upstream_change.py` 的 `stages` 集合需要把 `"narrative"` 加进去，这是对已有文件的一处小改动）。
  - 提示词内容要点：narration 要能被 beats 的 cue_text 精确拼接覆盖（校验会检查）；beat 拆分建议粒度（design §5.2 的字段含义：`cue_text`/`visual_action`/`emphasis`/`transition`）；写完后先跑 `validate_narrative`，通过后再跑 `synthesize_tts`；`synthesize_tts` 可以只传改动过的 `scene_ids` 避免重新生成全部音频；`suggest_upstream_change` 用于发现选题简报有问题时提回上游。
- **测试**：见「接口与要点」的取舍说明；至少保证 `tools()` 返回的工具名称集合正确（`{"validate_narrative","synthesize_tts","suggest_upstream_change"}`）。
- **完成标准**：`pytest backend/tests/stages/` 全通过；`prompt.md` 人工审阅一遍，风格与 `animation/prompt.md` 一致。
- **验证命令**：`make check`

### T8：端到端 turn 测试——叙事 agent 全流程（待开始）

- **目标**：用 `FakeRuntime` 跑一轮完整的叙事阶段对话（写 `narrative.json` → `validate_narrative` → `synthesize_tts` → 用户在前端点"定稿"，测试里直接调用 `stage_flow.finalize`），验证动画阶段能从 `upstream/narrative/` 读到一致 schema 的产物并跑通已有的 `validate_scenes`（M2）。这条测试是"叙事产物真的能喂给动画阶段"的契约保证，避免 T1–T7 各自测试通过但拼起来对不上。
- **涉及文件**：新建 `backend/tests/api/test_narrative_flow.py`；可能需要给 `FakeRuntime` 的测试脚本机制加一个新的固定剧本（如果现有的 `FakeRuntime` 已经支持"按步骤调用给定工具"的通用剧本格式就不用改，只是新写一份剧本数据；先看 `backend/src/studio/agent/fake.py` 现有能力，不够用时才改，改动记入决策记录）。
- **接口与要点**：
  - 用 T4 的 `seed_narrative_project` 起步（叙事阶段 `active`）。
  - `FakeRuntime` 剧本：写 `narrative/narrative.json`（用一份和 `backend/tests/fixtures/animation/narrative.json` 结构一致但走真实工具调用产生 `timing.json` 的镜头数据）→ 调用 `validate_narrative` → 调用 `synthesize_tts`（`scene_ids=None`，用 T6 测试里同款的假 `TTSEngine`）→ `TurnEnd`。
  - 断言：turn 结束后 `narrative/timing.json` 存在且字段形状与 M2 fixture 一致；调用 `stage_flow.finalize(..., "narrative")` 后，动画阶段状态从 `locked`/`stale` 变为 `active`；`materialize_upstream` 到动画阶段的工作区后，直接调用 `stages.animation.validate_scenes` 的内部读取函数（或整个工具）验证能正确解析出镜头 id 列表（不要求这一步真的通过 manim 校验，因为还没写镜头代码，只验证"结构读得懂"）。
- **测试**：如上。
- **完成标准**：`pytest backend/tests/api/test_narrative_flow.py` 通过。
- **验证命令**：`make check`

### T9：`agent.preamble`——按镜头 id 的上游变更摘要（TD-6）（待开始）

- **目标**：`_upstream_changes` 对"叙事→动画"这一条边，解析新旧两份 `narrative/narrative.json` 内容，给出按镜头 id 的新增/删除/旁白变化/beat 变化摘要；其余上下游边（目前只有"选题→叙事"）行为不变，仍是文件级 diff。
- **涉及文件**：`backend/src/studio/agent/preamble.py`（改 `UpstreamChange` dataclass 加一个可选字段、改 `_upstream_changes`、改 `build_preamble` 的渲染分支）、`backend/tests/agent/test_preamble.py`（已存在，补新用例）。
- **接口与要点**：
  - `UpstreamChange` 新增字段 `scene_summary: list[str] | None = None`（默认 `None`，不影响其它调用点的现有断言）。
  - 新函数 `_narrative_scene_summary(old_manifest, new_manifest, blobs) -> list[str] | None`：只在 `old_manifest`/`new_manifest` 都包含 `narrative/narrative.json` 且能成功 `json.loads` 时才返回摘要列表；任何一步失败（缺文件、JSON 非法、缺 `id` 字段）都返回 `None`（调用方据此退回文件级 diff，不让前言生成因为一个解析失败而报错整轮）。
    - 摘要规则：按 `id` 对比两份 `scenes[]`：新出现的 id → "新增镜头 {id}"；消失的 id → "删除镜头 {id}"；两边都有但 `narration` 不同 → "镜头 {id} 旁白有改动"；`narration` 相同但 `beats` 列表（按内容整体比较，不细分哪个 beat）不同 → "镜头 {id} 的 beat 拆分有改动"；两者都相同的 id 不出现在摘要里。
  - `_upstream_changes` 里，仅当 `name == "narrative"` 时调用 `_narrative_scene_summary`；结果非 `None` 时用它填 `UpstreamChange.scene_summary`，`diff` 字段仍然照常计算（保留给以后可能需要的场景，渲染时优先用 `scene_summary`）。
  - `build_preamble` 的"上游新定稿"渲染分支：`change.scene_summary` 非 `None` 时输出它（每行一条），否则退回现有的 `_file_summary(change.diff)`。
  - 这一处改动不涉及 `agent.stage.StageDefinition` Protocol，不需要 `stages.animation`/`stages.narrative` 任何代码改动（`agent` 层直接按已知的 JSON 结构解析，不 import `stages`，符合 ARCHITECTURE §2 规则 2）。
- **测试**：两份 `narrative.json`（新增一个镜头、删除一个镜头、某镜头 narration 改了、某镜头 beats 改了、完全没变）分别断言摘要文本；`old`/`new` 缺 `narrative/narrative.json`（例如选题→叙事这条边）时 `scene_summary is None` 且 `build_preamble` 输出退回文件级摘要（用已有的"选题→叙事"用例验证不受影响）。
- **完成标准**：`pytest backend/tests/agent/test_preamble.py` 通过。
- **验证命令**：`make check`

### T10：前端 `features/canvas/narrative/`——叙事画布（待开始）

- **目标**：叙事阶段的画布能显示镜头卡片列表（旁白、每个 beat 的 cue_text/visual_action/emphasis/transition、校验状态）、选中镜头的音频播放条（按 beat 起止时间分段标记）、原始 JSON 标签页（复用 `CodeEditor.vue`，只读或可编辑均可，参照动画画布"代码编辑器"任务的取舍）；"配音是否最新"用当前 `narrative.json` 的 `narration` 和 `timing.json` 是否覆盖该镜头做前端判断（不需要新后端接口）。
- **涉及文件**：
  - 新建 `frontend/src/features/canvas/narrative/NarrativeCanvas.vue`（外壳：镜头列表 + 详情面板 + JSON 标签页切换，参照 `AnimationCanvas.vue` 的整体结构）。
  - 新建 `frontend/src/features/canvas/narrative/SceneCardList.vue`（镜头卡片，参照 `SceneList.vue`）。
  - 新建 `frontend/src/features/canvas/narrative/BeatTimeline.vue`（音频播放条 + beat 分段刻度）。
  - 新建 `frontend/src/features/canvas/narrative/narrativeDoc.ts`（纯逻辑：解析 `narrative/narrative.json` 文本为 `{id, narration, visual_intent, beats}[]`，参照 `narrativeScenes.ts` 但要解析完整字段，不只是 id）+ `narrativeDoc.spec.ts`。
  - 新建 `frontend/src/features/canvas/narrative/timingStatus.ts`（纯逻辑：给定解析后的 narrative 和 `narrative/timing.json` 文本，算出每个镜头是"未配音/配音最新/配音过期（narration 改过但没重新合成）"三态之一，以及整体 `alignment_coverage`）+ `timingStatus.spec.ts`。
- **接口与要点**：
  - "配音过期"判定：`timing.json` 目前没有存 narration 的哈希/文本（M2 fixture 里没有），无法直接比较。方案：`timingStatus.ts` 只依据"该镜头 id 是否存在于 `timing.json.scenes[]`"判定"未配音"，不尝试判定"过期"（决策：M3 不新增 `timing.json` 的字段来支持过期检测，避免和 T6 已定的 timing.json 形状产生分歧；"配音是否随最新旁白更新"这件事留给 agent 自己判断——它能读到 `synthesize_tts` 是否被再次调用过——用户侧的"过期"提示留到发现有真实需求时再加，记入 `docs/quality/tech-debt.md`）。
  - 音频播放：`<audio>` 元素 `src` 指向后端文件下载/读取端点——需要确认现有 `api/files.py` 是否已支持读工作区内任意文件的字节（生成音频文件的场景类似前端读 `.mp4`/关键帧图片的既有能力，检查后决定是否需要新端点；如果已有通用的"读工作区文件字节"端点就直接复用，不新增）。
  - JSON 标签页：直接复用 `components/CodeEditor.vue`（`features/canvas/animation/AnimationCanvas.vue` 已经证明可以跨 `features/canvas/*` 复用它，见 ARCHITECTURE §3 决策记录 D36）。
- **测试**：`narrativeDoc.spec.ts`/`timingStatus.spec.ts` 覆盖正常解析、字段缺失、JSON 语法错误（抛出交给调用方处理，参照 `narrativeScenes.ts` 的既有约定）；组件本身走 L4 浏览器验证，不做挂载测试（沿用 M2 的前端测试策略）。
- **完成标准**：`pytest frontend`（vitest）通过；L4 浏览器走查见 T11。
- **验证命令**：`make check`

### T11：`ProjectWorkbenchPage.vue` 接入叙事画布 + L4 走查（待开始）

- **目标**：`stage === 'narrative'` 时渲染 `NarrativeCanvas`（而不是通用文件画布），完整走一遍"手工选题简报 fixture → 打开项目 → 叙事阶段对话（Fake 或真实 Claude 订阅登录）→ 校验/配音 → 定稿 → 动画阶段能看到上游变更摘要"的路径。
- **涉及文件**：`frontend/src/pages/ProjectWorkbenchPage.vue`（加一个 `v-else-if="stage === 'narrative'"` 分支，参照现有 `animation` 分支的写法）。
- **接口与要点**：无新接口，纯装配。
- **测试**：无新增自动化测试（装配性改动）；用 `make dev` + Claude 桌面版内置浏览器手动走查，按「验证记录」要求截图：镜头卡片列表、音频播放条、JSON 标签页、定稿按钮状态随校验/配音结果变化、动画阶段打开时能看到"上游新定稿"里按镜头 id 的摘要文本。
- **完成标准**：L4 走查全部通过，截图存 `data/evidence/m3-narrative/`。
- **验证命令**：`make dev` 手动走查

### T12：文档与配置收尾（待开始）

- **目标**：`.env.example`、`docs/references/`、`docs/quality/tech-debt.md`（T10 提到的"配音过期检测"缺口登记）按 SOP §10 的触发表更新。
- **涉及文件**：`backend/.env.example`（若 T1 未顺手写完）、新建 `docs/references/volcengine-tts.md`（记录真实调用中观察到的行为——例如流式分片顺序、时间戳精度、mp3 时长解析在极短文本下的表现——冒烟测试跑完（T13）后再填，注明日期和来源）、`docs/quality/tech-debt.md`（补"配音过期检测"条目）。
- **接口与要点**：无。
- **测试**：`scripts/check_docs.py`（`make check` 已包含的文档检查）通过。
- **完成标准**：`make check` 通过（文档检查项）。
- **验证命令**：`make check`

### T13：真实 Volcengine TTS 冒烟测试（待开始）

- **目标**：`backend/tests/smoke/test_smoke.py` 新增 `test_volcengine_tts`（`@pytest.mark.smoke`），用真实 `VOLCENGINE_TTS_API_KEY` 直接调用 `VolcengineTTSEngine.synthesize`（不经 `TurnRunner`，因为这不是模型对话，是引擎层的直接调用），验证真实合成返回非空音频、`duration_seconds` 合理、`word_timestamps` 非空；再跑一次 `align_scene_beats` 验证真实时间戳下的对齐覆盖率处于合理区间（不要求 1.0，真实语音识别时间戳可能有缺口）。
- **涉及文件**：`backend/tests/smoke/test_smoke.py`（新增用例）、`Makefile`（`smoke` 目标的 `env -i` 白名单加 `VOLCENGINE_TTS_API_KEY`，和现有的 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`DEEPSEEK_API_KEY` 并列）、`docs/runbooks/verification.md`（冒烟测试用例表格加一行）。
- **接口与要点**：
  - 缺 `VOLCENGINE_TTS_API_KEY` 时用例 `pytest.skip`，不报失败（沿用其它冒烟用例"缺 key 就跳过"的约定）。
  - 用一句很短的中文文本（例如"这是一次语音合成测试"），控制真实费用和运行时间。
  - 结果按现有约定写一份到 `data/evidence/m1/smoke/` 还是新开 `data/evidence/m3-narrative/smoke/` 目录——沿用现有 `test_smoke.py` 里其它用例的落盘路径写法（读代码后确定，不额外新建目录规则）。
- **测试**：即用例本身。
- **完成标准**：本机设置 `VOLCENGINE_TTS_API_KEY` 后 `make smoke SMOKE_ARGS="-k volcengine_tts"` 通过；未设置 key 时该用例显示 `SKIPPED`。
- **验证命令**：`make smoke SMOKE_ARGS="-k volcengine_tts"`

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-09-29 — T1 `engines.tts` 协议与 Volcengine 引擎迁移 — 14 个测试通过，`make check` 全绿（commit `20bf088`）
- 2026-09-29 — T2 `beat_aligner`/`text_normalize` 迁移 — 6 个测试通过，`make check` 全绿（commit `6b24bf4`）
- 2026-09-29 — T3 `stages.narrative.schema` — 6 个测试通过，`make check` 全绿（commit `cca221d`）
- 2026-09-29 — T4 选题简报 fixture + `seed_narrative_project` + `conftest.py` 的 `narrative_project` fixture — 4 个测试通过，`make check` 全绿（commit `2eea76e`）
- 2026-09-29 — T5 `validate_narrative` 工具 — 5 个测试通过，`make check` 全绿（commit `58bec39`）
- 2026-09-29 — T6 `synthesize_tts` 工具 — 6 个测试通过，`make check` 全绿（commit `b3714b6`）

- 2026-09-29 — T7 叙事阶段 tools 接入 + 完整提示词（顺带补 T6 返回文本的时长/覆盖率）— `make check` 全绿（commit `dde6697`）

## 下一步

- 从 T8 开始：新建 `backend/tests/api/test_narrative_flow.py`，用 `FakeRuntime` 跑叙事阶段完整一轮（写 `narrative.json` → `validate_narrative` → `synthesize_tts`，用 `monkeypatch` 替换 `synthesize_tts_module._ENGINE_FACTORY` 为假引擎）→ `stage_flow.finalize` → 动画阶段读 `upstream/narrative/`。先读 `backend/src/studio/agent/fake.py` 看现有剧本能力，不够用再改并记入决策记录。假 `TTSEngine` 可参考 `backend/tests/stages/test_narrative_synthesize.py` 里的 `FakeTTSEngine`。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-09-29：起草计划时定下的关键设计选择（供执行时对照，不算正式决策记录，执行中如与实际情况不符以执行时的决策记录为准）：
  - TTS API key 走裸环境变量 `VOLCENGINE_TTS_API_KEY`（无 `STUDIO_` 前缀），不进 `Settings`，理由是和 `model_profiles.api_key_env` 的"真实 key 不落进配置字段"原则保持一致，且 TTS 只有一个供应商，不需要 `model_profiles` 那种多档位间接层。
  - `beat_aligner` 丢弃 `fallback_weight` 字段，插值统一等权重——新 narrative schema 没有这个字段，属于对旧系统的简化迁移。
  - `timing.json` 的 `beats[].start_seconds/end_seconds` 取对齐后的"发言起止时间"（`speech_start/end`），不叠加 `animation_start/end` 的 pre/post-roll——和 M2 已有 fixture 的取值方式保持一致，避免改动 `render_preview` 的既有假设。
  - "叙事→动画"上游变更摘要按镜头 id 的解析逻辑放在 `agent/preamble.py` 内部（硬编码只处理 `name == "narrative"` 这一条边），不修改 `agent.stage.StageDefinition` Protocol——范围收得更紧，符合 TD-6 里"在 `agent/preamble.py` 里改"的原始建议。
  - "配音是否过期"（narration 改了但没重新合成）不在本计划实现检测，只做"是否配过音"的判断；过期检测登记进 tech-debt，留给出现真实需求时再做。
- 2026-09-29（T1 执行中）：`build_tts_engine()` 改成无参数（计划草稿里写的是 `(*, voice, speed)`）——音色/语速本来就要按 `TTSRequest` 逐次传给 `synthesize()`，构造引擎时接收这两个参数只会是死参数，不使用。改动范围只在这一个函数签名，不影响其它任务。
- 2026-09-29（T1 执行中）：mp3 时长解析测试没有 mock `mutagen`，而是生成了一个真实的极短 mp3（`ffmpeg`/`lame`，本机开发环境已有）存成二进制 fixture `backend/tests/fixtures/tts/tiny.mp3`（2.4KB，已提交）。理由：`_parse_mp3_duration` 的正确性依赖 mutagen 真的能解析出时长，mock 掉会让"时间戳按真实时长夹紧"这条关键行为测不到；测试本身运行时不再需要 `ffmpeg`/`lame`（只读预生成的文件），不影响可移植性。

- 2026-09-29（T6 执行中）：假引擎注入用模块级 `_ENGINE_FACTORY`（默认 `build_tts_engine`），测试 `monkeypatch.setattr` 替换——不改 `ToolContext`/`ToolSpec` 签名，改动最小。
- 2026-09-29（T6 执行中）：`timing.json` 的镜头顺序按 `narrative.json` 中的顺序写出（不是按 id 字母序）；不在当前 narrative 里的旧条目原样追加在末尾；本次没有任何镜头成功时不写 `timing.json`，避免留下空文件。

- 2026-09-29（T7 执行中）：提示词轻量断言单独放 `tests/stages/test_narrative_prompt.py`（与 `test_animation_prompt.py` 对称），工具集合断言放进 `test_placeholders.py` 的 `TestNarrativeStage`；`test_common.py` 里 `suggest_upstream_change` 的阶段范围断言同步改为 `{"animation","narrative"}`。
- 2026-09-29（T7 执行中）：补 T6 遗漏——`synthesize_tts` 返回文本里每个成功镜头带时长和对齐覆盖率（计划 T6 第 8 步原本就要求，提示词也依赖它），加了断言。

## 意外与发现

<!-- 和预期不一致的事、SDK 的新发现（同时写进 references/）、临时绕过的问题（同时登记到 tech-debt）。 -->

- 无

## 阻塞

<!-- 触发 SOP §6 升级条件时填写：问题、已尝试的办法、可选方案和推荐。解决后保留记录，并注明怎么解决的。 -->

- 无

## 验证记录

<!-- 自验证阶段填写：每条验收标准对应的命令、输出摘要、截图路径。 -->

- 无
