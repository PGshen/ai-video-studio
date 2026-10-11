# free-mode：自由模式（直接创建的单阶段项目）

<!-- 本计划实现 docs/design/2026-10-12-free-mode.md。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 自由模式（非编号） |
| 设计依据 | [自由模式设计](../../design/2026-10-12-free-mode.md) |
| 分支 | `feat/free-mode`（从 `main` 的 `1850787` 切出，设计文档已在其上） |
| 批准记录 | 2026-10-12：负责人批准计划，同意 D1 |
| 执行方式 | 本会话内联（Native），完成后一个独立评审检查整个分支 |

## 目标

用户可以在项目页直接新建「自由讲解 / 自由短片 / 自由 MV」项目（也可以从选题卡创建）。项目只有一个对话阶段：agent 联网、可以读写整个工作区，按用户说的做；实时预览、成片和成片定稿照常可用。多阶段项目的行为不变。

## 范围

**包含：**

- `ProjectKind.mode`、自由形态的流水线与预设、创建接口。
- 配音工具迁到 `stages.common.narration`；工具的时间轴来源从按阶段名分支改为查表。
- 共享提示词片段（多阶段提示词逐字不变）。
- `free_explainer`、`free_produce` 两个阶段，以及 api 中所有按阶段名判断的地方。
- 前端：新建入口、选题卡的自由卡片、工作台画布扩展、单阶段导航、设置页的阶段默认模型。
- 测试、真实模型冒烟、L4 浏览器验收、ADR 0029 与文档同步。

**不包含：**

- 自由项目与多阶段项目之间的转换；创建后修改形态；讲解 + 导入音乐。
- `timeline` schema、worker、渲染引擎、预览接口主体逻辑的改动（设计 §5.5）。

## 全局约束

- 设计 §2：创建时选形态；直接创建只给自由模式；选题卡可以建自由项目；不加额外的成片关口；联网；agent 照用户说的做、不清楚先问。
- 阶段名固定为 `free_explainer`（界面名「自由讲解」）、`free_produce`（界面名「自由创作」）；流水线分别为 `["free_explainer"]`、`["free_produce"]`。
- `mode` 取值 `"staged" | "free"`，缺失或非法时按 `staged`；创建后只读。
- 各阶段之间互不 import（import-linter 契约）：自由阶段要复用的东西先挪进 `stages.common`。
- 多阶段的 `narrative`、`animation_html`、`produce`、`music` 提示词拼接结果与重构前逐字相同。
- 不用 `skip`、`xfail`、`# type: ignore`、`noqa` 绕过失败；每个任务结束 `make check` 为绿，至少一个 commit，格式 `<type>(<scope>): <中文说明>`。
- 不引入新依赖；工作区里不用 git。

## 审查重点

这些是设计隐含、但各任务测试不一定覆盖的输入或状态，每条都在对应任务里有一条测试：

1. **老项目**：settings 里没有 `mode`（或取值非法）的项目，流水线、工作台和渲染行为与现在完全一致（T1、T9）。
2. **自由讲解改稿后不一致**：`narrative.json` 改了、没有重新配音；或者重新配音后配乐的 `base_hash` 对不上。场景工具和 `render_music` 要点名问题，成片前置检查要拒绝（T3、T6）。
3. **agent 改了不该改的文件**：通过 Shell 改 `style/STYLE.md`、`narrative/timing.json`、`music/music.wav` 或写进 `uploads/`，回合结束时要还原；写 `notes/`、`animation/`、`foo/bar.md` 要保留（T5、T6）。
4. **自由 MV 还没有歌曲**：第一轮对话时 `status_summary` 提示先上传歌曲，`render_music` 和 `analyze_music` 给出明确错误；对话进行中上传返回 409（T5、T7）。
5. **用选题卡创建自由项目**：卡片写到 `free_*/notes/idea-card.md`，卡片状态和项目的 `idea_id` 与多阶段创建一致；客户端在 `settings` 里塞的 `mode`、`pipeline` 被丢弃（T1、T7）。

## 验收标准

- [ ] AC1：`POST /projects` 可以用 `mode=free` 创建三种自由形态（带或不带 `idea_id`），流水线、settings、卡片路径正确；非法组合返回 422 且没有副作用；老项目按 `staged` 处理。（验证：`tests/stages/test_pipeline.py`、`tests/api/test_projects.py`、`tests/api/test_video_kinds.py`）
- [ ] AC2：多阶段的四个提示词逐字不变；`narrative` 阶段的现有测试全部通过；import-linter 通过。（验证：`tests/stages/test_prompt_fragments.py`、`make check`）
- [ ] AC3：fake 运行时下，自由讲解（含带背景乐）、自由短片、自由 MV 都能从创建走到渲染任务成功、成片定稿、项目完成。（验证：`tests/api/test_free_flow.py`）
- [ ] AC4：自由阶段的可写范围、工具清单、联网、时间轴来源符合设计 §4、§5。（验证：`tests/stages/test_free_explainer_stage.py`、`test_free_produce_stage.py`、`test_timeline_source.py`）
- [ ] AC5：前端可以在项目页新建自由项目、在选题卡建自由项目；工作台显示设计 §6.2 的标签页，默认打开「预览」；单阶段项目不显示阶段条。（验证：vitest 用例）
- [ ] AC6：真实模型冒烟：自由讲解与自由短片各出一次成片；自由讲解的第一轮先给方案或提问。（验证：`make smoke SMOKE_ARGS="-k free"`，用本机 Claude 登录）
- [ ] AC7：L4：浏览器里走一遍新建 → 对话 → 预览 → 成片 → 定稿，附截图。
- [ ] AC8：`make check` 全绿；ADR 0029、ARCHITECTURE、glossary、QUALITY、TODO 已同步。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：项目模型与创建接口（完成）

- **目标**：`mode` 进入项目类型；能创建自由项目（这时阶段还没注册，`video-kinds` 显示为不可用，创建返回 422。这是现有"未注册阶段"的逻辑，T5、T6 注册后自动变为可用）。
- **涉及文件**：`backend/src/studio/stages/pipeline.py`、`backend/src/studio/api/schemas.py`（`ProjectCreate.mode`、`ProjectKindOut.mode`、`ProjectKindConfig.mode`）、`backend/src/studio/api/projects.py`、`backend/src/studio/api/video_kinds.py`（`STAGE_TITLES` 加两项、预设与配置列表输出 `mode`）、`backend/tests/stages/test_pipeline.py`、`backend/tests/api/test_projects.py`、`backend/tests/api/test_video_kinds.py`。
- **接口与要点**：
  - `Mode = Literal["staged", "free"]`；`ProjectKind(engine, narration, music_source, mode="staged")`，`mode` 放在最后并带默认值，现有调用不用改。
  - `kind_errors`：`mode == "free"` 且有旁白时 `music_source` 不能为 `import`。
  - `build_pipeline`：`free` 时有旁白返回 `["free_explainer"]`，否则返回 `["free_produce"]`。
  - `valid_kinds()` 追加四种自由组合；`PRESETS` 追加三张卡片（`Preset` 加 `mode` 字段，默认 `staged`），文案见设计 §3.2。
  - `KIND_SETTING_KEYS`、`kind_settings`、`kind_from_settings` 加 `mode`。
  - 创建接口：`mode` 与 `engine`/`narration`/`music_source` 一起校验，规则是"全不给 = 默认，只给一部分 → 422"，`mode` 本身可以单独缺省（缺省为 `staged`）。卡片路径沿用 `<pipeline[0]>/notes/idea-card.md`。
- **测试（先写）**：四种自由组合的流水线；自由讲解 + 导入报错；`kind_from_settings` 遇到缺失或非法的 `mode` 时返回 `staged`（审查重点 1）；`kind_settings` 往返一致；创建接口在自由阶段未注册时返回 422 且没有目录和项目行（用一个注册了假 `free_*` 阶段的 registry 夹具验证创建成功的路径）；客户端 settings 里的 `mode`/`pipeline` 被丢弃（审查重点 5）；`video-kinds` 含三张自由卡片。
- **完成标准**：上述测试通过；多阶段的现有测试不变。
- **验证命令**：`make check`

### T2：配音工具迁到 `stages.common.narration`（待开始）

- **目标**：纯重构，让自由阶段能用 `synthesize_tts` 和 `validate_narrative`。
- **涉及文件**：移动 `backend/src/studio/stages/narrative/{synthesize_tts,validate_narrative,schema}.py` → `backend/src/studio/stages/common/narration/`（新增 `__init__.py` 导出 `SYNTHESIZE_TTS_TOOL`、`VALIDATE_NARRATIVE_TOOL`、`validate_and_normalize`、`NarrativeValidationError`）；`stages/narrative/__init__.py` 改 import；全仓搜索 `stages.narrative.schema`、`stages.narrative.synthesize_tts` 的调用方（含 `tests/`、`api/`）并改正。
- **接口与要点**：行为、工具名、文案都不变；工具的 `stages={"narrative"}` 在 T3 统一调整。
- **测试**：现有 `test_narrative_schema.py`、`test_narrative_synthesize.py`、`test_narrative_validate.py` 只改 import 路径，全部通过；import-linter 通过。
- **完成标准**：`grep -rn "stages.narrative.schema\|stages.narrative.synthesize_tts\|stages.narrative.validate_narrative"` 没有结果。
- **验证命令**：`make check`

### T3：时间轴来源表与工具的阶段归属（待开始）

- **目标**：工具按"来源方式"取时间轴，不再写死 `ctx.stage == "produce"`；为两个自由阶段开放工具。
- **涉及文件**：`backend/src/studio/stages/common/timeline_source.py`（新）、`stages/common/scenes/helpers.py`、`stages/common/score/tool.py`、`stages/common/scenes/validate_scenes_html.py`、`stages/common/scenes/render_preview_html.py`、`stages/common/score/analyze.py`、`stages/common/narration/*.py`、`stages/common/web_tools.py`（工具的 `stages` 集合）、`backend/tests/stages/test_timeline_source.py`（新）、`test_produce_scene_tools.py`、`test_produce_music_tools.py`、`test_animation_html_tools.py`、`test_music_tool.py`。
- **接口与要点**：
  - `TimelineSourceKind = Literal["upstream", "live_silent", "live_narrated"]`；`timeline_source(stage: str) -> TimelineSourceKind`：`produce`、`free_produce` 返回 `live_silent`；`free_explainer` 返回 `live_narrated`；其余返回 `upstream`。
  - `load_live_narrated(workdir, *, with_music: bool) -> LoadedTimeline`：`TimelineSources(workdir, narration=True, music_source="synth" if (workdir/"music/events.json").is_file() else "none", with_music=with_music)`，`prefix=""`。
  - `scenes/helpers.load_timeline(ctx)`：按来源分派。`live_narrated` 时 `with_music=True`；没有 `events.json` 时退化为纯旁白。
  - `render_music`：`live_silent` 走现有 `produce` 路径；`live_narrated` 用 `load_live_narrated(with_music=False)` 的 `timeline` 和 `base_hash`；`upstream` 不变。
  - `stages` 集合：场景两个工具加 `free_explainer`、`free_produce`；`render_music` 加两者；`analyze_music` 加 `free_produce`；配音两个工具加 `free_explainer`；联网工具加两者。
- **测试（先写）**：`timeline_source` 的映射表；`free_explainer` 下场景工具从顶层读（只有 `narrative/` 时只有旁白层；有 `events.json` 时叠加配乐层）；`render_music` 在 `free_explainer` 下写出的 `render.json.base_hash` 等于顶层不含配乐层的哈希；**审查重点 2**：`narrative.json` 改了但没有重新配音时，场景工具返回点名 `timing.json` 的错误；`produce` 和 `animation_html` 的现有工具测试不变。
- **完成标准**：`grep -rn 'ctx.stage == "produce"' backend/src` 没有结果。
- **验证命令**：`make check`

### T4：共享提示词片段（待开始）

- **目标**：契约类段落只维护一份；多阶段提示词逐字不变。
- **涉及文件**：`backend/src/studio/stages/common/prompts/`（新，含 `__init__.py` 和若干 `.md`）、`stages/{narrative,animation_html,produce,music}/prompt.md` 与对应 `__init__.py` 的 `system_prompt()`、`backend/tests/stages/test_prompt_fragments.py`（新）、`backend/tests/stages/fixtures/prompts_before/`（重构前四份提示词的原文，作为临时对照）。
- **接口与要点**：
  - `compose_prompt(*parts: str) -> str`：按顺序读 `stages/common/prompts/<name>.md` 和阶段自己的 `.md`，用固定分隔拼接。阶段的 `prompt.md` 拆成"开场白"文件加片段名列表。
  - 候选片段：叙事 `narrative-schema`（结构、beats 字段与粒度）、`style-files`、`narration-tools`；画面 `scene-contract`（env 契约、技术选择、时间规则、确定性规则、画面规则）；配乐 `compose-contract`；歌曲 `song-analysis`、`song-lyrics`。**只有在两个阶段里逐字相同的段落才合并**；不相同的保留各自版本，自由阶段在 T5、T6 里选一个版本引用，并在「决策记录」写明选了哪个。
  - 与阶段绑定的说法（读 `upstream/…`、"只能写 X"）留在开场白里。
- **测试（先写）**：四个阶段的 `system_prompt()` 与 `prompts_before/` 中的原文逐字相等；`compose_prompt` 遇到不存在的片段名报错。
- **完成标准**：测试通过后在同一任务内删掉 `prompts_before/` 对照文件，改为对每个片段做内容存在性断言（锁住关键句），避免固定对照文件长期存在。
- **验证命令**：`make check`

### T5：`free_produce` 阶段（待开始）

- **目标**：自由短片、自由 MV 能跑起来（agent 侧）。
- **涉及文件**：先把 `stages/produce/blockers.py`、`stages/produce/prepare.py` 挪到 `stages/common/produce_flow/`（`finalize_blockers`、`status_summary`、`prepare_turn`），`stages/produce/__init__.py` 改 import；新增 `stages/free_produce/{__init__.py,opening.md}`；`stages/common/free_scope.py`（新，两个自由阶段共用的 `WriteScope` 构造与公共提示词片段 `free-mode.md`）；`backend/src/studio/main.py`（注册）；`backend/src/studio/db/repo/settings.py`（`STAGES` 加两个自由阶段）；`backend/src/studio/api/animation_stage.py`、`backend/src/studio/api/scene_checks.py`；`backend/tests/stages/test_free_produce_stage.py`（新）、`test_produce_stage.py`（只改 import）。
- **接口与要点**：
  - `free_write_scope(extra_tool_managed: Sequence[str]) -> WriteScope`：`writable=["*"]`，`tool_managed` = 配乐产物 + 上传 + `style/**` + 参数里的额外项（设计 §4.3）。
  - `FreeProduceStage`：`name="free_produce"`、`allow_web=True`、`reads()=[]`、`tools()` 见设计 §5.3、`prepare_turn` 复用 `produce_flow.prepare_turn`、`artifact_dirs=["music","animation"]`、`finalize_blockers`/`status_summary` 复用 `produce_flow`。MV 还没有歌曲时，`status_summary` 第一行写"还没有歌曲：请用户在「配乐」标签页上传"。
  - 提示词：`compose_prompt("free-mode", "<free_produce 开场白>", …T4 的配乐/歌曲/画面片段)`。开场白说明：没有上游、按工作区内容判断形态、可以随意写 `notes/`。
  - `animation_stage_of`：流水线含 `free_produce` 或 `free_explainer` 时返回它，优先级排在 `produce`、`animation_html` 之前；`_CHECKED_STAGES` 加两者。
- **测试（先写）**：可写范围（审查重点 3：`notes/a.md`、`animation/scenes/s1.js`、`foo/bar.md` 可写；`style/STYLE.md`、`music/music.wav`、`music/source.mp3`、`uploads/x` 不可写）；工具名集合；`allow_web`；`reads()==[]`；`prepare_turn` 只写 `upstream/exemplar/`（MV 多一份歌词样本）；还没有歌曲时的 `status_summary`（审查重点 4）；`animation_stage_of` 对自由流水线的返回值；`produce` 现有测试不变。
- **完成标准**：`video-kinds` 中自由短片、自由 MV 变为可用。
- **验证命令**：`make check`

### T6：`free_explainer` 阶段（待开始）

- **目标**：自由讲解（含带背景乐）能跑起来（agent 侧）。
- **涉及文件**：`stages/free_explainer/{__init__.py,opening.md}`、`backend/src/studio/main.py`、`backend/tests/stages/test_free_explainer_stage.py`（新）。
- **接口与要点**：
  - `FreeExplainerStage`：`name="free_explainer"`、`allow_web=True`、`reads()=[]`、`write_scope=free_write_scope(["narrative/timing.json","narrative/audio/**"])`、工具见设计 §5.3、`artifact_dirs=["narrative","music","animation"]`。
  - `prepare_turn`：只复制 `CANVAS_EXEMPLAR`、`WEBGL_EXEMPLAR` 到 `upstream/exemplar/`；有 `music/compose.py` 时再复制 `AUDIO_EXEMPLAR`；不写 `upstream/timeline.json`。
  - `status_summary`：镜头数（`narrative.json`）、配音是否覆盖每个镜头（`timing.json` 与 `narrative.json` 是否一致，复用 `narration_from_documents` 的错误）、`scenes/` 覆盖、配乐 `render.json` 的 `base_hash` 是否等于当前顶层哈希。读不出的项写"未知"或"还没有"，不抛异常。
  - `finalize_blockers`：见决策记录 D1（草案）。
  - 提示词：`compose_prompt("free-mode", "<free_explainer 开场白>", "style-files", "narrative-schema", "narration-tools", "scene-contract", 可选背景乐片段)`。开场白说明：没有简报，事实靠联网核实；时间轴由 `narrative.json` + 配音生成，场景 id 等于镜头 id；改稿后要重新配音。
- **测试（先写）**：可写范围（审查重点 3：`narrative/narrative.json`、`notes/outline.md` 可写；`narrative/timing.json`、`narrative/audio/s1.mp3`、`style/STYLE.md` 不可写）；工具集合；`prepare_turn` 的两种情况；`status_summary` 在空工作区、只有叙事、叙事与配音不一致（审查重点 2）、配乐过期四种情况下的文本；提示词包含关键片段的锚点句。
- **完成标准**：`video-kinds` 中自由讲解变为可用。
- **验证命令**：`make check`

### T7：api 端到端流程（待开始）

- **目标**：fake 运行时下三种自由形态都能从创建走到成片定稿。
- **涉及文件**：`backend/tests/api/test_free_flow.py`（新）；按需修改 `backend/src/studio/api/projects.py`、`api/music_import.py`、`api/files.py`（只修测试暴露出的问题，不预先改）。
- **接口与要点**：
  - 用例：（a）自由讲解：创建 → fake 一轮写 `narrative.json` 并调用 TTS（用测试里已有的假 TTS）→ 写场景 → `POST /render` → worker 用测试替身后端跑完 → `finalize-render` → 项目 `completed`；（b）自由讲解 + 背景乐，多一步 `render_music`；（c）自由短片；（d）自由 MV：上传歌曲 → 分析 → 镜头 → 渲染。
  - 选题卡创建自由项目：卡片路径、卡片状态与多阶段一致（审查重点 5）。
  - 对话进行中上传歌曲返回 409（审查重点 4）；自由项目没有 `concept` 行时允许上传。
  - 文件接口：`PUT` 写 `notes/x.md` 成功，写 `style/STYLE.md` 返回 403。
- **测试（先写）**：即上面的用例，参照 `test_html_final_flow.py`、`test_synth_music_flow.py`、`test_music_upload.py` 的夹具写法。
- **完成标准**：四条流程全部通过。
- **验证命令**：`make check`

### T8：前端新建入口与类型选择（待开始）

- **目标**：项目页可以直接新建自由项目；选题卡可以选自由形态；各处认识两个新阶段。
- **涉及文件**：`frontend/src/types/api.ts`（`mode`）、`frontend/src/features/projects/NewFreeProjectDialog.vue`（新）与 spec、`frontend/src/pages/ProjectsPage.vue`、`features/projects/ProjectList.vue`（空状态文案与顶部注释）、`features/projects/ProjectCard.vue`（"自由"标记）、`features/projects/projectView.ts`（阶段筛选认识两个新阶段）、`components/VideoKindPicker.vue` 与 spec、`composables/videoKindChoice.ts`、`features/ideas/CreateProjectDialog.vue`、`composables/stageTitles.ts`、`components/session/suggestionFlow.ts`（`STAGE_TITLES`）、`features/settings/settingsView.ts`（`DEFAULT_PROFILE_STAGES` 加两项）、`frontend/src/test/videoKindsFixture.ts`。
- **接口与要点**：
  - `NewFreeProjectDialog`：标题（必填）、形态三选一（数据来自 `useVideoKindsQuery`，只显示 `mode=free` 的预设；自由讲解多一个"加背景乐"开关）、`StyleSelect`、`EffortSelect`；提交 `{title, mode:"free", engine, narration, music_source, style_preset_id, settings:{effort}}`，成功后跳到 `/projects/{id}/{pipeline[0]}`。
  - `VideoKindPicker`：按 `mode` 分两组显示（"分阶段"/"自由"），选题卡对话框两组都显示；项目页的新建对话框只用自由组。
  - 不可用的卡片照现有方式显示原因。
- **测试（先写）**：新建对话框只列自由形态、讲解的背景乐开关映射到 `music_source`、提交的请求体、跳转路径；Picker 分组；项目页有「新建项目」按钮；`STAGE_TITLES` 含两个新阶段。
- **完成标准**：vitest 通过；`make check` 的前端 lint、类型检查通过。
- **验证命令**：`make check`

### T9：前端工作台画布（待开始）

- **目标**：自由阶段的工作台显示设计 §6.2 的标签页。
- **涉及文件**：`frontend/src/features/canvas/animation/HtmlAnimationCanvas.vue` 与 spec、`frontend/src/pages/ProjectWorkbenchPage.vue`、`features/workbench/StageNav.vue` 与 spec、`features/canvas/stageActions.ts`、`features/canvas/narrative/NarrativeCanvas.vue`（加 `hideFinalize` 之类的属性，按现有写法）、`features/canvas/music/ImportMusicCanvas.vue`（确认 `allow-upload` 在自由 MV 下为 true 时的行为）、`features/canvas/generic/FileCanvas.vue`（作为插槽嵌入时的高度和布局）。
- **接口与要点**：
  - `HtmlAnimationCanvas` 的 `stage` 属性类型扩展为 `'animation_html' | 'produce' | 'free_explainer' | 'free_produce'`；新增插槽 `#narrative`、`#files`；标签页的显示规则和默认页（自由阶段为 `preview`）抽成纯函数 `canvasTabs(stage, slots) -> {tabs, initial}`，便于单测。
  - `produceNotStarted` 的提示语只对 `produce` 生效（自由阶段没有 concept 可以等）。
  - 工作台页：两个自由阶段走 `HtmlAnimationCanvas`，插槽按 `project.kind`（旁白、配乐来源）填充；MV 的 `ImportMusicCanvas` 设 `allow-upload`。
  - `StageNav`：`stages.length === 1 && kind.mode === 'free'` 时不显示阶段条，显示"自由模式 · 讲解 / 短片 / MV"。
  - `STAGES_WITH_OWN_ACTIONS` 加两个自由阶段。
  - `FileCanvas` 的只读判断不变（保存时由后端的 403 兜底，设计 §6.2 末条的确认结果写进决策记录）。
- **测试（先写）**：`canvasTabs` 四个阶段的标签页与默认页；工作台在 `free_explainer`（有配乐/无配乐）、`free_produce`（短片/MV）下渲染出对应插槽；`StageNav` 单阶段显示；**审查重点 1**：多阶段项目的 `StageNav` 和画布快照不变。
- **完成标准**：vitest 通过。
- **验证命令**：`make check`

### T10：冒烟、L4 与文档（待开始）

- **目标**：真实模型和浏览器验证；文档同步。
- **涉及文件**：`backend/tests/smoke/test_free_mode_smoke.py`（新）、`docs/decisions/0029-自由模式单阶段项目.md`（新）、`docs/ARCHITECTURE.md`、`docs/glossary.md`、`docs/quality/QUALITY.md`、`docs/plans/TODO.md`、`docs/runbooks/verification.md`（如冒烟命令有新增）。
- **接口与要点**：
  - 冒烟（用本机 Claude 登录，`-k free`）：自由讲解第一轮只给题目，断言没有写出 `animation/scenes/*.js`，回复里含问题或方案；第二轮"按这个做，60 秒以内"，断言产出 `narrative.json`、`timing.json`、场景，然后触发渲染得到 `final.mp4`。自由短片一句话需求 → 成片。自由 MV 复用 `test_music_video_smoke.py` 的歌曲夹具，验证到 `validate_scenes_html` 通过。
  - L4：`make dev`，内置浏览器里新建自由短片 → 对话 → 预览 → 成片 → 定稿；再看一个自由讲解项目的「叙事」和「文件」标签页。截图写进「验证记录」。
  - ADR 0029：两个阶段而不是一个 `free`；`writable=["*"]` 与 `style/**` 借 `tool_managed` 只读；时间轴来源查表；提示词片段化。
- **完成标准**：AC6、AC7、AC8 有证据。
- **验证命令**：`make check`；`make smoke SMOKE_ARGS="-k free"`

## 进度

- 2026-10-12 — T1 — `mode` 进入项目类型，自由形态流水线与预设，创建接口与 video-kinds 输出 `mode`

## 下一步

- 从 T2 开始（配音工具迁到 `stages.common.narration`）。

## 决策记录

- 2026-10-12 — **D1（负责人 2026-10-12 同意）**：设计 §4.2 写的是 `free_explainer` 的 `finalize_blockers`"组合叙事与场景检查"，但现有 `narrative` 和 `animation_html` 的 `finalize_blockers` 都返回 `[]`，成片的正确性由 worker 前置检查和 `finalize-render` 的快照核对保证。建议 `free_explainer` 同样返回 `[]`，配音和配乐是否最新通过 `status_summary` 告诉 agent。理由：没有现成的检查可以组合；成片定稿本来就要求先渲染成功，再加一层是重复检查。`free_produce` 照设计复用 `produce` 的检查。
- 2026-10-12 — **D3**（T1）：T1 原计划的"自由阶段未注册时创建返回 422"测试没写：红线不允许 `skip`，而 T5、T6 注册真实阶段后这条测试就不成立了；未注册阶段返回 422 的逻辑已有通用测试 `test_unavailable_kind_is_422_and_leaves_nothing`。改为用 `register_free_stages`（假阶段）测成功路径。
- 2026-10-12 — **D2**：`produce` 的 `blockers.py`、`prepare.py` 挪到 `stages/common/produce_flow/`（T5）。设计 §4.2 写的是"复用"，但阶段之间不能互相 import，只能先挪到 `common`。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 无
