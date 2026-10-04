# pipeline-config：项目类型与按项目派生的阶段流水线（多形态视频 子项目 1）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成 |
| 里程碑 | 多形态视频流水线 · 子项目 1/4 |
| 设计依据 | [多形态视频流水线设计](../../design/2026-10-04-html-video-pipeline.md) §2、§3、§11；[ADR 0020](../../decisions/0020-阶段流水线按项目配置派生.md) |
| 分支 | `pipeline-config` |
| 批准记录 | 2026-10-04：负责人批准设计与 ADR 0020/0021，要求开始写本计划；2026-10-04：负责人批准本计划，选择 Subagent-driven 执行；2026-10-04：负责人验收通过，合并到 main |

> 执行者：按 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行；本计划的「进度」「决策记录」就是账本。每个任务先写失败的测试，再实现。

## 目标

把"固定三阶段、静态上下游"改成"创建项目时选视频类型 → 派生阶段流水线 → 上下游按项目解析"，为后续的 HTML 引擎、配乐、节拍脚本阶段打好地基。本计划结束时：

- 创建项目对话框可以选视频类型（四个预设，讲解类可选配乐来源）；阶段尚未实现的组合显示为不可用并说明原因。
- 阶段流转（解锁、定稿、stale、前言里的上游变化、回退建议）支持一个阶段有多个上游。
- 现有 Manim 讲解项目（包括老项目）行为不变，`make check` 为绿。

## 范围

**包含：**

- 纯函数模块 `studio.stages.pipeline`：项目类型配置、合法性规则、`build_pipeline`、预设目录。
- 阶段协议：`upstream_stages()` → `reads()`；新增 `prepare_turn(workdir)` 钩子；`StageRegistry.has()`；`agent` 层 `upstream_of`、`project_pipeline`。
- 迁移 0009：`project_stages.based_on`（`{上游阶段: 快照 id}`）取代 `based_on_snapshot_id`。
- `stage_flow`、`preamble`、TurnRunner 的多上游改造与 `prepare_turn` 调用。
- api：创建项目接收类型配置、`GET /api/video-kinds`、`ProjectOut.kind`、`StageOut.based_on`。
- 前端：创建项目对话框的类型选择、新阶段中文名、项目信息展示类型、创建后跳转到 `current_stage`。
- `ARCHITECTURE.md`、`QUALITY.md` 同步。

**不包含：**

- 任何新阶段（`concept`、`beatsheet`、`music`、`animation_html`）的实现——子项目 2～4。本计划只让它们的 key 出现在流水线派生和中文名里。
- `studio.timeline`、HTML 引擎、配乐——子项目 2～4。
- 设置页"各阶段默认模型"加入新阶段 key（`db/repo/settings.py` 的 `STAGES`）——随各阶段的子项目加入。
- 新阶段的工作区画布——新阶段落到通用画布即可（`ProjectWorkbenchPage` 现有的回退分支）。
- 真实模型冒烟：本计划不改任何提示词和工具行为。

## 全局约束

- 合法性规则（设计 §2.2）：`narration=false` 时 `music_source ≠ none`；`narration=false` 时 `engine = html`。
- 合法配置恰好 8 种：`engine ∈ {manim, html}` × `narration=true` × `music_source ∈ {none, synth, import}`，加上 `html` × `narration=false` × `music_source ∈ {synth, import}`。
- `video_kind` 由配置派生，不单独接收：有旁白 → `explainer_manim`/`explainer_html`（按引擎）；无旁白 → `motion_reel`（synth）/`music_video`（import）。
- 流水线（设计 §3.2）："谁定时间谁在前"：
  - 有旁白：`topic → narrative → [music] → animation|animation_html`
  - `motion_reel`：`concept → beatsheet → music → animation_html`
  - `music_video`：`concept → music → beatsheet → animation_html`
- 各阶段的 `reads()`（设计 §3.3）：`topic=[]`、`concept=[]`、`narrative=[topic]`、`beatsheet=[concept, music]`、`music=[concept, narrative, beatsheet]`、`animation=[narrative]`、`animation_html=[narrative, beatsheet, music]`、`brainstorm=[]`、`style=[]`。本计划只改已存在阶段的声明；新阶段的值写在 `pipeline.py` 的测试替身里用于验证。
- 老项目（`settings` 里没有类型字段）：视为 `engine=manim, narration=true, music_source=none`，不做 settings 数据迁移；流水线取 `project_stages` 行的创建顺序。
- 类型字段创建后只读：`PATCH /projects/{id}/settings` 的白名单不变；创建时客户端 `settings` 里的 `video_kind`/`engine`/`narration`/`music_source`/`pipeline` 一律丢弃，由服务端写入。
- 新依赖：无。
- 分层：`studio.stages.pipeline` 只依赖标准库（加一条 import-linter `forbidden` 契约禁止它 import `studio` 其他模块）；`agent` 仍不 import `stages`。

## 评审重点

规格隐含、但最容易在实际使用中出问题的五类情况（每条都已在对应任务里加了测试）：

1. **老项目升级**：迁移前已经有 `based_on_snapshot_id`、处于 `stale` 的叙事/动画阶段，迁移后定稿、stale 判断、前言上游变化都和迁移前一致（T3）。
2. **多上游提前解锁**：只定稿多个上游中的一个时，下游必须仍是 `locked`（短片里定稿 `concept` 不能解锁 `music`）（T3）。
3. **多上游 stale 恢复**：一个上游改回原样、另一个上游仍有变化时，下游必须保持 `stale`；所有上游都对得上时才回到 `active`（T3）。
4. **选了不可用的组合**：创建请求里的配置合法但阶段未注册（例如讲解 + 合成配乐），返回 422 和可读原因，不留下工作区目录、快照或项目行（T5）。
5. **客户端夹带类型字段**：`settings` 里塞 `pipeline`/`video_kind`/`engine`，服务端不采纳（T5）。

## 验收标准

- [x] AC1：`build_pipeline` 对 8 种合法配置给出设计 §3.2 的流水线，非法组合返回中文错误（验证方式：`tests/stages/test_pipeline.py`）
- [x] AC2：`upstream_of` 对短片、MV、讲解 + 配乐、老项目给出设计 §3.3 的上游（验证方式：`tests/agent/test_stage.py`）
- [x] AC3：多上游流转：全部上游定稿才解锁；按上游分别判断 stale 与恢复；`after_turn_done` 记录每个上游的版本（验证方式：`tests/agent/test_stage_flow.py`，用假阶段）
- [x] AC4：迁移 0009 把老数据的 `based_on_snapshot_id` 正确回填为 `based_on`，升级和降级都能跑（验证方式：`tests/db/` 迁移测试）
- [x] AC5：TurnRunner 每轮按项目流水线物化 `upstream/`、给工具上下文传正确的直接上游、在物化之后调用 `prepare_turn`（验证方式：`tests/agent/test_runner*.py`）
- [x] AC6：`POST /projects` 接收类型配置、写入派生字段、按上游设置初始状态；不可用组合 422 且无残留；`GET /api/video-kinds` 返回预设与 8 种配置的可用性（验证方式：`tests/api/test_projects.py`、新 `tests/api/test_video_kinds.py`）
- [x] AC7：创建项目对话框可选类型，不可用的卡片/选项禁用并显示原因，创建后跳到项目的 `current_stage`；项目信息里显示类型（验证方式：前端单测 + L4 截图）
- [x] AC8：现有 Manim 流程不变：现有后端、前端测试全部通过；`ARCHITECTURE.md`、`QUALITY.md` 已更新；`make check` 为绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：项目类型与流水线派生（完成）

- **目标**：AC1。
- **涉及文件**：
  - 新建 `backend/src/studio/stages/pipeline.py`
  - 新建 `backend/tests/stages/test_pipeline.py`
  - 修改 `backend/pyproject.toml`（`[tool.importlinter]` 新增契约："`studio.stages.pipeline` 只依赖标准库"，`forbidden_modules` 列 `studio.config`、`studio.db`、`studio.agent`、`studio.workspace`、`studio.engines`，以及 `studio.stages` 下各阶段包）
- **接口**（产出，后续任务依赖这些名字）：
  - `Engine = Literal["manim", "html"]`、`MusicSource = Literal["none", "synth", "import"]`、`VideoKind = Literal["explainer_manim", "explainer_html", "motion_reel", "music_video"]`
  - `@dataclass(frozen=True) class ProjectKind: engine: Engine; narration: bool; music_source: MusicSource`
  - `LEGACY_KIND: ProjectKind`（manim / True / none）
  - `KIND_SETTING_KEYS: tuple[str, ...] = ("video_kind", "engine", "narration", "music_source", "pipeline")`
  - `kind_errors(kind: ProjectKind) -> list[str]`：中文错误，合法时为空
  - `video_kind_of(kind: ProjectKind) -> VideoKind`
  - `build_pipeline(kind: ProjectKind) -> list[str]`：非法时抛 `ValueError`（消息为 `kind_errors` 拼接）
  - `valid_kinds() -> list[ProjectKind]`：8 种，顺序固定（先有旁白 manim/html × none/synth/import，再 motion_reel、music_video）
  - `@dataclass(frozen=True) class Preset: video_kind: VideoKind; label: str; description: str; music_choices: tuple[MusicSource, ...]; default: ProjectKind`
  - `PRESETS: tuple[Preset, ...]`：四个预设；讲解类 `music_choices = ("none", "synth", "import")`，短片 `("synth",)`，MV `("import",)`
  - `kind_from_settings(settings: Mapping[str, Any]) -> ProjectKind`：缺字段返回 `LEGACY_KIND`
  - `kind_settings(kind: ProjectKind) -> dict[str, Any]`：要写入 `projects.settings` 的五个键（含 `video_kind`、`pipeline`）
- **要点**：只依赖标准库；`label`/`description` 是界面直接显示的中文（"知识讲解（Manim）""知识讲解（HTML）""动态图形短片""音乐 MV"，description 各一句话说明形态）。
- **测试**（先写，确认失败）：
  - 8 种合法配置逐个断言流水线（参数化，期望值照抄"全局约束"）。
  - `kind_errors`：无旁白 + 无配乐、无旁白 + manim 各返回一条错误；两者同时违反返回两条。
  - `video_kind_of` 四种派生；`valid_kinds()` 长度 8，且每个都通过 `kind_errors`。
  - `kind_from_settings({})` 是 `LEGACY_KIND`；`kind_from_settings(kind_settings(k)) == k` 对 8 种都成立。
  - `PRESETS` 里每个预设的 `default` 合法，且 `video_kind_of(default) == preset.video_kind`。
- **完成标准**：用例通过，lint-imports 通过。
- **验证命令**：`cd backend && uv run pytest tests/stages/test_pipeline.py -q && uv run lint-imports`

### T2：阶段协议：`reads()`、`prepare_turn`、`upstream_of`（完成）

- **目标**：AC2。
- **涉及文件**：
  - `backend/src/studio/agent/stage.py`：协议与注册表
  - 各阶段 `backend/src/studio/stages/{topic,narrative,animation,brainstorm,style}/__init__.py`：`upstream_stages` 改名为 `reads`（返回值不变），新增空的 `prepare_turn`
  - 测试替身：`backend/tests/agent/test_stage.py`、`tests/agent/test_runner.py`（约第 675、732、787 行的三个内联假阶段）、`tests/smoke/support.py:138`、`tests/stages/test_placeholders.py`、`tests/stages/test_style_stage.py`
  - 新增测试放在 `backend/tests/agent/test_stage.py`
- **接口**：
  - `StageDefinition.reads(self) -> list[str]`（取代 `upstream_stages`）
  - `StageDefinition.prepare_turn(self, workdir: Path) -> None`：每轮刷新 `upstream/` 之后调用；文档字符串写明"只允许写 `upstream/` 下的派生文件"
  - `StageRegistry.has(self, name: str) -> bool`
  - `upstream_of(pipeline: Sequence[str], registry: StageRegistry, stage: str) -> list[str]`（`agent/stage.py`）：`stage` 不在 `pipeline` 或未注册时返回 `[]`；结果按流水线顺序；`reads()` 里出现但不在流水线、或排在 `stage` 之后的阶段被排除
- **要点**：这一步只改名和加方法，不改任何调用方的行为——`stage_flow`、`preamble`、`runner` 暂时改成调用 `reads()`（行为与原 `upstream_stages()` 相同），T3/T4 再换成 `upstream_of`。`ToolContext.upstream_stages`/`TurnContext.upstream_stages` 字段名不改（语义是"直接上游"）。
- **测试**（先写）：在测试里注册 `concept`/`beatsheet`/`music`/`animation_html` 四个假阶段（`reads()` 按"全局约束"），断言：
  - 短片流水线：`upstream_of(..., "music") == ["concept", "beatsheet"]`，`"animation_html" → ["beatsheet", "music"]`
  - MV 流水线：`"music" → ["concept"]`，`"beatsheet" → ["concept", "music"]`，`"animation_html" → ["music", "beatsheet"]`
  - 讲解 + 配乐 `[topic, narrative, music, animation]`：`"music" → ["narrative"]`，`"animation" → ["narrative"]`
  - 老项目 `[topic, narrative, animation]`：与原 `upstream_stages` 结果一致
  - 不在流水线的阶段 → `[]`；`registry.has("nope") is False`
- **完成标准**：新用例通过；全量后端测试不变绿（纯改名）。
- **验证命令**：`cd backend && uv run pytest -q && uv run lint-imports`

### T3：多上游的阶段流转与迁移 0009（完成）

- **目标**：AC3、AC4；评审重点 1～3。
- **涉及文件**：
  - 新建 `backend/src/studio/db/migrations/versions/0009_project_stages_based_on.py`
  - `backend/src/studio/db/models.py`（`ProjectStage`：新增 `based_on: JSON`，默认 `{}`；删除 `based_on_snapshot_id`）
  - `backend/src/studio/db/repo/stages.py`（`StageValue.based_on: dict[str, str]`；`update_stage(..., based_on: dict[str, str] | None = None)` 整体替换；去掉 `based_on_snapshot_id` 参数）
  - `backend/src/studio/agent/stage_flow.py`
  - `backend/src/studio/agent/preamble.py`（`_upstream_changes`）
  - `backend/src/studio/api/projects.py`、`backend/src/studio/api/animation.py`、`backend/src/studio/api/schemas.py`（`StageOut.based_on: dict[str, str]` 取代 `based_on_snapshot_id`）
  - 测试：`backend/tests/agent/test_stage_flow.py`、`tests/agent/test_preamble.py`、`tests/db/` 下新增迁移测试、受影响的 api 测试
- **接口**：
  - `project_pipeline(engine: Engine, project_id: str) -> list[str]`（`stage_flow.py`）：`settings["pipeline"]` 存在则用它，否则用 `list_stages` 的顺序（老项目）
  - `stage_flow` 内部的上下游统一走 `upstream_of(project_pipeline(...), registry, stage)`；因此 `upstream_snapshot_ids`、`upstream_sources` 签名改为 `(engine, registry, project_id, stage_name: str)`
  - `initial_statuses(pipeline: Sequence[str], registry: StageRegistry) -> list[tuple[str, str]]`：没有上游的阶段 `active`，其余 `locked`（T5 用）
  - `after_turn_done(engine, project_id, stage, used_upstream: dict[str, str | None])`：语义见要点
- **要点**：
  - **迁移 0009**：加 `based_on` 列（JSON，非空，默认 `{}`）；回填规则：`based_on_snapshot_id` 非空时，`narrative` 行写 `{"topic": id}`，`animation` 行写 `{"narrative": id}`（迁移前只存在这两种有上游的阶段）；然后用 batch 模式删掉旧列。降级时反向：取 `based_on` 的任意一个值写回旧列。
  - **解锁**：上游 X 定稿后，对每个下游 D（X ∈ `upstream_of(D)`）：D 为 `locked` 时，只有 D 的**全部**上游都已定稿才变 `active`，并把 `based_on` 设为全部上游当前的定稿快照 id。
  - **stale 判断**：D 不是 `locked` 时，逐个上游 U 比较 `based_on[U]` 对应快照与 U 当前定稿快照在 U 产物目录下的内容（沿用 `_upstream_artifacts_changed`，缺失按"有变化"）；任一上游有变化 → `stale`；全部无变化且原来是 `stale` → `active`；否则不动。抽成私有函数 `_reconcile(engine, registry, project_id, row)`，`finalize` 对每个下游调用。
  - **`after_turn_done`**：`based_on` 更新为本轮开始时物化的全部已定稿上游 `{U: id}`（`None` 的跳过）；只有每个用到的 id 都等于该上游当前定稿 id 时，`stale` 才回到 `active`。删掉"M1 每个阶段最多一个上游"的说明。
  - **前言**：`_upstream_changes` 对每个上游 U 用 `based_on.get(U)` 作为旧版本（缺失则跳过该上游），与 U 当前定稿比较。
- **测试**（先写，确认失败）：
  - 迁移：在 0008 状态下插入带 `based_on_snapshot_id` 的 `narrative`、`animation`、`topic`（空）行，升级到 0009 后 `based_on` 分别为 `{"topic": …}`、`{"narrative": …}`、`{}`；再降级回 0008，旧列值恢复。
  - **评审重点 1**：老项目（无 `settings.pipeline`）走完 topic 定稿 → narrative 定稿 → 重新打开 topic 并修改 → 重新定稿，animation 不受影响、narrative 变 `stale`，前言里出现 topic 的变化——与改造前的既有用例结论一致（既有用例全部保留并通过）。
  - **评审重点 2**：假阶段短片流水线：定稿 `concept` 后，`beatsheet` 变 `active`、`music` 仍 `locked`；再定稿 `beatsheet`，`music` 变 `active` 且 `based_on` 同时含 `concept`、`beatsheet`。
  - **评审重点 3**：`music` 基于 `{concept: S1, beatsheet: S2}`；重新打开并修改 `concept` 后定稿 → `music` 为 `stale`；再修改 `beatsheet` 后定稿 → 仍 `stale`；把 `concept` 改回原样再定稿 → 仍 `stale`（`beatsheet` 还在变）；把 `beatsheet` 也改回原样定稿 → `active`。
  - `after_turn_done`：两个上游，一个在轮中又定稿了 → 状态保持 `stale`，`based_on` 记录本轮用到的版本。
  - `initial_statuses`：短片 → `[concept active, beatsheet locked, music locked, animation_html locked]`；MV 同理只有 `concept` 为 active。
- **完成标准**：新老用例全部通过；`grep -rn based_on_snapshot_id backend/src` 只剩迁移文件。
- **验证命令**：`cd backend && uv run pytest -q && uv run lint-imports`

### T4：TurnRunner 接入项目流水线与 `prepare_turn`（完成）

- **目标**：AC5。
- **涉及文件**：`backend/src/studio/agent/runner.py`（`_execute` 约第 313–357 行；`_execute_workspaceless`、`_execute_bound_dir` 的 `upstream_stages` 参数）、`backend/src/studio/agent/turn_finish.py`（第 82 行附近对 `after_turn_done` 的调用，签名不变则只核对）、测试 `tests/agent/test_runner.py`、`tests/agent/test_runner_suggestion.py`。
- **要点**：
  - 项目轮次：`state.upstream_ids = stage_flow.upstream_snapshot_ids(engine, registry, project_id, job.stage.name)`；物化 `upstream/` 之后调用 `job.stage.prepare_turn(workdir)`，**在构建前言之前**；`prepare_turn` 抛异常时本轮按现有的失败路径结束（错误事件里带阶段名和异常信息），不吞掉。
  - `TurnContext.upstream_stages = tuple(upstream_of(project_pipeline(engine, project_id), registry, job.stage.name))`。
  - 无工作区和绑定目录模式：`upstream_stages=()`，不调用 `prepare_turn`。
  - TurnRunner 若当前不持有 `StageRegistry`，在构造参数里加上（`main.py` 装配处同步改，测试工厂同步改）。
- **测试**（先写）：
  - 假阶段的 `prepare_turn` 记录调用时 `upstream/` 是否已物化（断言已物化）、调用次数为每轮一次；无工作区阶段不调用。
  - `prepare_turn` 抛异常 → 轮次 `failed`，错误事件含异常信息。
  - 讲解 + 配乐假流水线 `[topic, narrative, music, animation]` 中，`music` 的工具上下文 `upstream_stages == ("narrative",)`；既有 `test_runner_suggestion` 三条断言不变。
- **完成标准**：用例通过；既有 runner 测试不变绿。
- **验证命令**：`cd backend && uv run pytest tests/agent -q`

### T5：api：按类型创建项目与 `GET /api/video-kinds`（完成）

- **目标**：AC6；评审重点 4、5。
- **涉及文件**：`backend/src/studio/api/projects.py`、`backend/src/studio/api/schemas.py`、新建 `backend/src/studio/api/video_kinds.py`（并在 `main.py` 注册路由）、`backend/src/studio/db/repo/projects.py`（`create_project` 增加 `current_stage: str` 参数）、测试 `tests/api/test_projects.py`、新建 `tests/api/test_video_kinds.py`。
- **接口**：
  - `ProjectCreate` 新增可选 `engine: Engine | None`、`narration: bool | None`、`music_source: MusicSource | None`；三者都不给时使用 `LEGACY_KIND`，只给一部分时 422（"类型配置需要同时提供 engine、narration、music_source"）。
  - `ProjectOut` 新增 `kind: ProjectKindOut`（`video_kind`、`engine`、`narration`、`music_source`、`pipeline`），由 `kind_from_settings` 派生，老项目同样有值（`pipeline` 取 `project_pipeline`）。
  - `GET /api/video-kinds` → `VideoKindsOut { presets: [PresetOut{video_kind, label, description, music_choices, default}], kinds: [KindOptionOut{engine, narration, music_source, video_kind, pipeline, available: bool, unavailable_reason: str | null}] }`；`available` = 流水线里每个阶段都 `registry.has`；不可用原因形如"「配乐」阶段尚未实现"（用阶段中文名，中文名表放在 `api/video_kinds.py`，与前端 `STAGE_TITLES` 一致）。
- **要点**（创建流程顺序与"失败不留半成品"的约定不变）：
  1. 解析类型 → `kind_errors` 非空 422；流水线有未注册阶段 422（同上不可用原因）——这两步在建工作区**之前**。
  2. 客户端 `settings` 里丢弃 `KIND_SETTING_KEYS`（与现有丢弃 `_STYLE_SETTING_KEYS` 同处理），再合并 `kind_settings(kind)`。
  3. 想法卡片路径改为 `f"{pipeline[0]}/notes/idea-card.md"`（讲解类仍是 `topic/notes/idea-card.md`）；`IDEA_CARD_PATH` 常量若有其他引用方，一并核对。
  4. `create_project(..., current_stage=pipeline[0])`；阶段行按 `initial_statuses(pipeline, registry)` 创建，替换 `_INITIAL_STAGES`。
- **测试**（先写）：
  - 不带类型字段创建 → `kind` 为 Manim 讲解、阶段行与改造前相同（三行、topic active）。
  - 显式 `manim/true/none` 创建 → `settings` 含五个类型键、`pipeline == [topic, narrative, animation]`。
  - **评审重点 4**：`manim/true/synth`（`music` 未注册）→ 422，响应包含"配乐"；数据目录下没有新工作区目录，`snapshots`/`projects`/`project_stages` 没有新行。
  - `html/false/none` → 422，含 `kind_errors` 的中文信息；只给 `engine` → 422。
  - **评审重点 5**：`settings={"pipeline": ["animation"], "video_kind": "music_video", "engine": "html"}` 且不给类型字段 → 项目仍是 Manim 讲解、`pipeline` 为三阶段。
  - 测试注册假的 `concept`/`beatsheet`/`music`/`animation_html` 后创建 `html/false/import` → 成功，阶段行顺序为 MV 流水线，只有 `concept` 为 active，`current_stage == "concept"`，想法卡片写在 `concept/notes/idea-card.md`。
  - `GET /api/video-kinds`：默认注册表下 8 种里只有 `manim/true/none` 可用，其余都有不可用原因；四个预设齐全。
  - `PATCH /projects/{id}/settings` 带 `engine` → 被现有白名单拒绝或忽略（与现有行为一致，补一条断言）。
- **完成标准**：用例通过；既有 api 测试通过。
- **验证命令**：`cd backend && uv run pytest tests/api -q && uv run lint-imports`

### T6：前端：类型选择、阶段名、项目信息（完成）

- **目标**：AC7。
- **涉及文件**：
  - `frontend/src/types/api.ts`（`ProjectCreate` 加三个可选字段；`ProjectOut.kind`；`StageOut.based_on` 取代 `based_on_snapshot_id`；`VideoKindsOut` 等）
  - `frontend/src/api/endpoints.ts`（`getVideoKinds`）、`frontend/src/composables/queries.ts`（`useVideoKindsQuery`，`staleTime: Infinity`）
  - 新建 `frontend/src/composables/videoKindChoice.ts` + `.spec.ts`（纯逻辑）
  - 新建 `frontend/src/components/VideoKindPicker.vue` + `.spec.ts`
  - `frontend/src/features/ideas/CreateProjectDialog.vue` + 其 spec
  - `frontend/src/composables/stageTitles.ts`（新增 `concept: '创意'`、`beatsheet: '节拍脚本'`、`music: '配乐'`、`animation_html: '动画'`）
  - `frontend/src/features/workbench/ProjectInfoBody.vue`（+ `projectInfo.ts`）
  - `frontend/src/features/workbench/ProjectSettingsDialog.vue`（+ 其 spec）
- **接口**：
  - `videoKindChoice.ts`：`findKind(kinds: KindOptionOut[], preset: PresetOut, music: MusicSource): KindOptionOut | undefined`、`initialSelection(data: VideoKindsOut): { videoKind: VideoKind; music: MusicSource }`（选第一个有可用配置的预设，配乐取该预设下第一个可用选项）、`presetAvailability(data, preset): { available: boolean; reason: string | null }`（预设下任一配乐选项可用即可用；全部不可用时取第一条原因）、`KIND_SUMMARY(kind: ProjectKindOut): string`（例如"知识讲解（Manim）· 有旁白 · 无配乐"）。规则全部来自后端返回的 `kinds`，前端**不复写**合法性规则与流水线。
  - `VideoKindPicker`：`v-model:videoKind`、`v-model:music`、prop `data: VideoKindsOut`；四张预设卡片（不可用卡片禁用，旁边显示原因）；当前预设 `music_choices` 多于一个时显示配乐下拉框，不可用选项禁用并以 title/说明文字显示原因；卡片下方显示所选配置的流水线（用 `STAGE_TITLES` 拼成"选题 → 叙事 → 动画"）。
- **要点**：
  - `CreateProjectDialog`：在风格选择上方放 `VideoKindPicker`；提交时带 `engine`/`narration`/`music_source`（从所选 `KindOptionOut` 取）；所选组合不可用时提交按钮禁用；创建成功后跳转改为 `/projects/${project.id}/${project.current_stage}`（替换写死的 `/topic`）。`video-kinds` 加载失败时显示错误、提交禁用。
  - `ProjectInfoBody` 在"基本信息"里加一行"视频类型"，显示 `KIND_SUMMARY`。
  - `ProjectSettingsDialog` 顶部加一行只读的"视频类型"（`KIND_SUMMARY` + 说明"创建后不能修改，换类型请新建项目"），设计 §2.3。
  - 用 shadcn-vue 现有组件（`RadioGroup` 或卡片按钮 + `Select`）；没有的组件用 CLI 添加，不手写到 `components/ui/`。
- **测试**（先写）：
  - `videoKindChoice.spec`：`initialSelection` 在只有 `manim/true/none` 可用时选中 Manim 讲解 + 无配乐；`presetAvailability` 对短片返回不可用和原因；`findKind` 找到对应配置。
  - `VideoKindPicker.spec`：渲染四张卡片；不可用卡片 `disabled` 且显示原因；切到 Manim 讲解后出现配乐下拉，"合成""导入"禁用；流水线文字为"选题 → 叙事 → 动画"。
  - `CreateProjectDialog.spec`：提交请求体含 `engine: 'manim', narration: true, music_source: 'none'`；成功后路由到返回项目的 `current_stage`（假后端返回 `current_stage: 'concept'` 时跳 `/concept`）。
  - `ProjectInfoBody.spec`、`ProjectSettingsDialog.spec`：显示类型摘要；设置对话框里没有可编辑的类型控件。
- **完成标准**：前端单测、类型检查、lint 通过。
- **验证命令**：`cd frontend && pnpm run lint && pnpm run typecheck && pnpm exec vitest run`

### T7：文档同步与 L4（完成）

- **目标**：AC8，并对 AC7 做真实浏览器走查。
- **涉及文件**：`docs/ARCHITECTURE.md`（`agent` 行：`reads`/`upstream_of`/`project_pipeline`/`prepare_turn`、多上游流转；`stages` 行：新增 `stages.pipeline`；`api` 行：`video_kinds`、创建项目的类型字段；分层规则段落：新的 import-linter 契约；前端 `components/VideoKindPicker`、`composables/videoKindChoice`）、`docs/quality/QUALITY.md`（`agent`、`api`、`frontend` 行的日期与说明）、`docs/quality/tech-debt.md`（执行中发现的新债）、本计划。
- **L4**（控制者在内置浏览器里做，隔离数据目录 + fake 运行时，不用真实 key）：① 选题池 → 创建项目，看到四张类型卡片，只有 Manim 讲解可选、其余显示"尚未实现"的原因，配乐下拉里只有"无"可选；② 创建后直接进入选题阶段，阶段导航为三段；③ 项目信息里显示"知识讲解（Manim）· 有旁白 · 无配乐"；④ 一个迁移前就存在的老项目打开正常、阶段状态不变。截图放进 `data/evidence/pipeline-config/`。
- **完成标准**：AC1～AC8 都有证据；计划状态改为待验收，经负责人验收后移到 `plans/completed/`。
- **验证命令**：`make check`

## 进度

- 2026-10-04 — 计划写成并获批准；从 main 建分支 `pipeline-config`，基线 `make check` 绿（f5c21cf）
- 2026-10-04 — T1 `stages/pipeline.py` 与 import-linter 契约，15 个用例先 RED（da2a487）
- 2026-10-04 — T2 `reads()`/`prepare_turn`/`StageRegistry.has`/`upstream_of`，纯改名不改行为（7002400）
- 2026-10-04 — T3 迁移 0009（`based_on` 映射）、多上游解锁与按上游 stale/恢复、前言按上游比较（f4f19ee）
- 2026-10-04 — T4 TurnRunner 按项目流水线解析上游、物化后调用 `prepare_turn`；顺带 `list_stages` 按 rowid 兜底排序、前言按 `artifact_dirs()` 截取（a3e2a5e）
- 2026-10-04 — T5 按类型创建项目、`GET /api/video-kinds`、`ProjectOut.kind`（3ade831）
- 2026-10-04 — T6 前端类型选择、阶段中文名、项目信息与设置里只读显示类型（9cd7212）
- 2026-10-04 — T7 ARCHITECTURE/QUALITY 同步（fdec501）；L4 在真实数据副本上走查通过
- 2026-10-04 — 整分支评审（Opus）：可以合并，0 Critical/Important；一次修复波处理 9 项（12e654d），复审全部 ADDRESSED；遗留登记为 TD-64～TD-68

## 下一步

- 下一份计划：子项目 2（时间轴 + HTML 引擎）。开工前先做设计 §12 的 spike（真实模型在无运行时库下写 Canvas 场景）。TD-64、TD-65 须在子项目 3 之前解决。

## 决策记录

- 2026-10-04：界面上不做"三个独立开关"，改为"四个预设 + 讲解类的配乐下拉"。理由：按设计 §2.2 的规则，合法配置只有 8 种，旁白和引擎都由预设唯一决定，唯一自由的维度是讲解类的配乐来源；三个开关只会多出一堆被禁用的组合。设计 §3.5 的"展开微调三个开关"按此落地。
- 2026-10-04：可用性由后端 `GET /api/video-kinds` 一次给出（8 种配置各自的流水线与是否可用），前端不复写规则和流水线，避免两边漂移。
- 2026-10-04：老项目不迁移 settings；流水线回退到 `project_stages` 的创建顺序（`current_stage_of` 已经依赖这个顺序）。只有 `based_on` 需要数据迁移，因为它的形状变了。
- 2026-10-04：`based_on` 改成按上游记录的映射，并且"全部上游定稿才解锁"。这两点设计文档没有写明，是在梳理 `stage_flow` 时发现的：原实现假设每个阶段最多一个上游（`after_turn_done` 只取第一个），任一上游定稿就解锁下游——在短片流水线里会让 `music` 在 `beatsheet` 定稿前就被解锁。属于 ADR 0020"上下游按项目解析"的必要实现细节，不另写 ADR。
- 2026-10-04：`build_pipeline` 放在 `studio.stages.pipeline`（独立模块，不属于任何阶段包），因为它知道阶段 key，不能放进 `agent`；它只依赖标准库，`api` 和测试都能直接用。

- 2026-10-04：执行用 SDD；分支直接建在当前检出（计划文件在提交前未跟踪）；任务标题是 `### T<n>`，brief 由控制者自行抽取。
- 2026-10-04：T5「PATCH 带 engine」的用例只断言类型与流水线不变，不断言状态码（计划写「与现有行为一致」；现有白名单返回 422）。
- 2026-10-04：T3 评审的两条小问题（`list_stages` 并列排序兜底、前言按 `artifact_dirs()` 截取）并入 T4 一起做，因为后者在上游目录名与阶段名不同时会让前言和 stale 判断看的文件不一致。
- 2026-10-04：整分支评审后的修复波除文字修正外，还做了：前端类型标签与后端 `PRESETS` 对齐、`kind_from_settings` 对非法值回落到 Manim 讲解（避免手改坏的设置让 `GET /projects` 500）、前言按流水线顺序列上游、创建对话框文案不再写死「选题打磨」。其余登记为技术债。

## 意外与发现

- 梳理 `stage_flow` 时发现原实现假设每阶段最多一个上游、任一上游定稿即解锁下游（已在决策记录说明并修复）。
- 评审指出两条早已存在的流转问题，在多上游下更容易遇到：定稿 `stale` 阶段不刷新自身 `based_on`（TD-64）、已定稿下游 stale 后上游改回原样落到 `active` 而不是 `finalized`（TD-65）。都不会卡死，但会多一次定稿、前言重复出现同一处变化；子项目 3 之前解决。
- `list_stages` 的并列排序测试写在实现之前就能通过（SQLite 本身按 rowid 稳定），保留为回归用例。

## 阻塞

- 无

## 验证记录

- AC1：`backend/tests/stages/test_pipeline.py`（先 RED：ModuleNotFoundError）。
- AC2：`backend/tests/agent/test_stage.py` 的 `upstream_of` 用例（短片、MV、讲解 + 配乐、老项目、不在流水线）。
- AC3：`backend/tests/agent/test_stage_flow.py`（多上游不提前解锁、四步 stale 恢复、`after_turn_done` 轮中上游又定稿、`initial_statuses`、老项目升级）。
- AC4：`backend/tests/db/test_migrate.py` 0008↔0009 升降级；L4 在真实数据副本上迁移，7 个老项目 `based_on` 回填正确。
- AC5：`backend/tests/agent/test_runner.py` 的 `TestPrepareTurn` 与流水线上游用例、`test_runner_suggestion.py` 原断言不变。
- AC6：`backend/tests/api/test_projects.py`、`tests/api/test_video_kinds.py`（不可用组合 422 且无残留、夹带类型字段被丢弃、MV 假阶段创建）。
- AC7：`VideoKindPicker.spec.ts`、`CreateProjectDialog.spec.ts`、`videoKindChoice.spec.ts`、`ProjectInfoBody`/`ProjectSettingsDialog` spec；L4 截图与记录 `data/evidence/pipeline-config/l4.md`。
- AC8：`make check` 绿（2026-10-04，修复波之后：后端约 1650、前端 914）。
