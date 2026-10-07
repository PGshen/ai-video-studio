# mv-lyrics：音乐 MV 的歌词联动

<!-- 本计划实现 docs/design/2026-10-07-mv-lyrics.md。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 完成 |
| 里程碑 | 多形态视频后续（produce 阶段之后） |
| 设计依据 | [mv-lyrics 设计](../../design/2026-10-07-mv-lyrics.md)（负责人 2026-10-07 批准） |
| 分支 | `feat/mv-lyrics`，从 main 切出（produce 阶段已合入 main） |
| 批准记录 | 2026-10-07：负责人批准计划，选择本会话内联执行；`feat/produce-stage` 已先合入 main（`560f131`），本分支从 main 切出 |
| 执行方式 | 本会话内联（不派子代理），完成后由一个独立评审检查整个分支 |

## 目标

用户在「创意与要求」阶段上传带时间戳的歌词（`.lrc`）；系统把它变成客观事实（每句的文字与起止时间）交给 `produce` 阶段；创意阶段由人确认「歌词意象」，制作阶段由模型自己画字幕、关键字与对应画面。

## 范围

**包含：** LRC 解析与 `LyricLine`；`Timeline.lyrics` 有类型化并按 `range` 截取；运行时 `env.lyrics`/`env.lyric()`；歌词上传/删除接口与 `analyze_music` 的歌词概况；`concept` 的「歌词意象」章节与检查；`produce` 的提示词、范例、预览采样、校验警告、`final.json.lyrics_hash`；前端上传区与歌词列表；文档、真实模型冒烟、L4。

**不包含：** 自动识别歌词；无时间戳的纯文本歌词；双语翻译；歌词编辑器；逐字时间；旧项目兼容；后端按阶段状态拒绝上传（TD-81 维持登记）；讲解类与合成短片的任何变化。

## 全局约束

- 设计 §2：歌词可选，没有歌词时 MV 的行为与哈希和改动前一致；字幕与关键字由模型自己画，系统只给数据与检查。
- `timeline` 保持纯能力层（不 import `agent`、`stages`）；LRC 解析放在 `timeline`；import-linter 契约不变，不放宽。
- 阶段之间互不 import：`concept` 与 `produce` 共用的代码放 `stages/common`。
- 外部行为以 `docs/references/` 为准；新发现补进 references，注明日期与来源。
- 不用 `skip`、`xfail`、`# type: ignore`、`noqa` 绕过失败；每个任务结束 `make check` 为绿，提交前**读完** `make check` 的结果；至少一个 commit，格式 `<type>(<scope>): <中文说明>`。
- 歌词是用户自己的文件，不进仓库；测试夹具用自编的短歌词。

## 审查重点

设计隐含、但各任务测试不一定覆盖的输入或状态，每条都在对应任务里有一条测试：

1. **LRC 常见的脏数据**：时间倒退、同一时刻多句、`[offset:]` 为负、BOM + CRLF、全是元信息没有歌词、一行里歌词含冒号或方括号（T1）。
2. **`range.json` 截取**：区间起点非零时歌词整体平移；跨界句裁剪；区间外丢弃；歌词整体在区间外时 `lyrics == []` 且不报错（T2）。
3. **无歌词的回归**：没有 `lyrics.lrc` 时时间轴哈希、`env.lyric()`、预览采样、提示词都与改动前一致（T2、T5）。
4. **`env.lyric()` 的边界**：第一句之前、最后一句之后、两句间隔 > 1 秒、同一时刻两句、`progress` 在句首为 0 句尾为 1（T2）。
5. **编造歌词**：简报「歌词意象」里整章都不是 LRC 里的原句时，`check_concept` 报错并点名（T4）。
6. **上传的并发与失败**：与歌曲接口一样的 409 与 422 路径；失败时不落盘、不改旧歌词（T3）。

## 验收标准

- [ ] AC1：`parse_lrc` 与 `Timeline.lyrics`、`env.lyrics`、`env.lyric()` 按设计 §3 工作，无歌词时与改动前行为一致。（验证：解析、时间轴、运行时测试，含真实 Chromium 的 `slow` 用例）
- [ ] AC2：歌词可上传、覆盖、删除；`analyze_music` 返回歌词概况；换歌词会让 `produce` 变 stale。（验证：接口测试与 stale 测试）
- [ ] AC3：有歌词时 `check_concept` 要求「歌词意象」，无歌词时不要求。（验证：`check_concept` 测试）
- [ ] AC4：`produce` 在有歌词时拷贝范例、提示词含歌词章节、预览采样含歌词起始、没有引用 `env.lyric` 时有警告；`final.json` 有 `lyrics_hash`。（验证：对应测试）
- [ ] AC5：前端上传区与歌词列表按设计 §6 显示。（验证：vitest 与 L4）
- [ ] AC6：真实模型冒烟——MV 带歌词走完 `concept → produce` 并出成片；简报含「歌词意象」，场景脚本引用 `env.lyric`；对照预览帧核对歌词句首时画面。听感与画面是否贴合歌词由负责人试听验收。
- [ ] AC7：`make check` 全绿，文档（ARCHITECTURE、QUALITY、glossary、references、TODO）同步。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：LRC 解析与 `LyricLine`（完成）

- **目标**：纯函数把 LRC 文本变成 `list[LyricLine]`，校验失败给明确原因。
- **涉及文件**：新增 `backend/src/studio/timeline/lyrics.py`；新增 `backend/tests/timeline/test_lyrics.py`。
- **接口与要点**：
  - `LyricLine(text, start, end)`（pydantic，放在 `timeline/schema.py`，T2 接入 `Timeline.lyrics`）；`parse_lrc(text: str, duration: float) -> list[LyricLine]`，失败抛 `LyricsError`（带逐条原因，风格同 `TimelineError`）。
  - 规则严格按设计 §3.1：多时间戳、`[offset:]`（正数让歌词提前）、元信息标签忽略、逐字标签去掉、空文本行为结束标记、结束 = 下一句开始、最后一句取 `min(start+5, duration)`、排序稳定。
  - 校验：BOM、大小 ≤ 200 KB（解析入口按字节数判断）、至少一句、无任何时间戳的纯文本拒绝、时间为负、时间晚于 `duration + 1` 秒。
- **测试（先写，表驱动）**：设计 §9 列出的全部解析情形，加审查重点 1。
- **完成标准**：`timeline` 的其余测试不变且通过；import-linter 契约保持。
- **验证命令**：`make check`。

### T2：时间轴与运行时（完成）

- **目标**：歌词进入时间轴并按区间截取；场景脚本能用 `env.lyrics`/`env.lyric()`。
- **涉及文件**：`backend/src/studio/timeline/schema.py`（`lyrics: list[LyricLine]`）、`timeline/load.py`（`_load_produce_import` 读 `music/lyrics.lrc`，按 `range` 截取并平移，传给 `build_timeline`）、`timeline/build.py`（`MusicInput`/`TimelineLayers` 带上歌词）、`backend/src/studio/engines/render/html/runtime.js`（`env.lyrics`、`env.lyric()`）、`engines/render/html/probe.py`（错误提示里列出新接口）；测试 `tests/timeline/test_load*.py`、`tests/engines/…` 里 `runtime` 相关用例与一个真实 Chromium 的 `slow` 用例。
- **接口与要点**：
  - 歌词不存在 → `lyrics == []`，且时间轴哈希与改动前完全一致（回归断言：同一输入前后哈希相等）；歌词存在 → 哈希包含歌词。
  - 截取规则：区间内保留；跨界句裁到区间内；区间外丢弃；整体都在区间外 → 空列表不报错。
  - `lyrics.lrc` 解析失败（文件被手工改坏）时时间轴加载给出点名文件的 `TimelineError`，不静默忽略。
  - `env.lyrics` 为本镜头内（与镜头区间有交集）的行，`start`/`end` 为镜头局部时间；`env.lyric()` 取当前正在唱或 ≤ 1 秒内刚唱完的一句，返回 `{ i, text, start, end, progress }`，没有则 `null`；无歌词给中性值，不抛错。
  - 合成短片与讲解类不读歌词（加载器不触碰该文件）。
- **测试（先写）**：审查重点 2、3、4；运行时在无歌词、有歌词两种时间轴下的行为；真实 Chromium 渲染一个引用 `env.lyric()` 的场景并断言文字出现时间。
- **完成标准**：讲解类与短片的时间轴、运行时测试全部不变且通过。
- **验证命令**：`make check`（含 `-m slow` 的相关用例单独跑一遍确认）。

### T3：上传接口、概况与托管文件（完成）

- **目标**：歌词可上传/覆盖/删除，分析结果带歌词概况，接口元数据返回歌词行。
- **涉及文件**：`backend/src/studio/api/music_import.py`（`POST`/`DELETE /projects/{id}/music/lyrics`，复用上传的忙与并发检查）、`api/music_import_meta.py` 与 `api/schemas.py`（`MusicMetaOut.lyrics`）、`backend/src/studio/stages/common/score/analyze.py`（工具文本附歌词概况）、`stages/concept/__init__.py` 与 `stages/produce/__init__.py`（`music/lyrics.lrc` 加入托管文件）、`stages/common/music_source.py`（放 `LYRICS_PATH` 常量与「找歌词文件」的小函数，供 `concept`/`produce` 共用）；测试 `tests/api/test_music_lyrics.py`、`tests/stages/` 里 `analyze_music` 的用例。
- **接口与要点**：
  - 上传：只接受 `music_source == "import"` 的项目（否则 404，同歌曲接口）；先在临时目录解析校验（用歌曲的 `duration`，来自 `analysis.json` 或 ffprobe；歌曲未上传则 422 并说明先传歌），成功后原子替换 `music/lyrics.lrc`；失败不改旧文件。
  - 删除：文件不存在返回 404 或幂等 204（选幂等，写进接口说明）。
  - 概况文本：行数、覆盖时长占比、最长无歌词间隔、是否超出歌曲；没有歌词时不输出这一段。
  - 元数据：返回歌词行（`text`、`start`、`end`），按 `range` 平移规则与 `shot_sections` 一致。
- **测试（先写）**：审查重点 6；非 UTF-8、纯文本、超限、歌曲未上传、非 MV 项目；`analyze_music` 有/无歌词的文本；写入范围测试确认模型不能直接写 `music/lyrics.lrc`；换歌词后 `produce` 变 stale（`stage_flow` 真实串联，参考 `test_produce_pipeline.py`）。
- **完成标准**：现有歌曲上传、元数据测试不变且通过。
- **验证命令**：`make check`。

### T4：`concept` 的「歌词意象」（完成）

- **目标**：有歌词时简报多一章「歌词意象」，并被检查。
- **涉及文件**：`backend/src/studio/stages/concept/check_concept.py`、`stages/concept/__init__.py`、`stages/concept/prompt.md`；测试 `tests/stages/test_concept*.py`。
- **接口与要点**：
  - 章节顺序：有歌词时「歌词意象」紧跟「视觉母题」之后；无歌词时 `SECTIONS` 与现在完全一致（八章）。`check_workspace` 按工作区里是否有 `music/lyrics.lrc` 决定。
  - 检查：有歌词且章节缺失或为空 → 错误；章节里至少逐字引用一句 LRC 里的原句（比较前去首尾空白，忽略全角半角空格）→ 否则错误，点名「没有引用任何真实歌词」；不要求覆盖每一句。
  - 提示词：新增歌词章节的写法与例子（逐句/逐段、画面隐喻、屏幕关键字、卡点；叙事类按段、抒情类按句）；强调统一视觉语言写在「视觉母题」里；告诉模型先读 `music/lyrics.lrc` 与 `analyze_music` 的概况；无歌词时不提这一章。
  - `status_summary` 在有歌词时提示「歌词 N 句」。
- **测试（先写）**：审查重点 5；有/无歌词两种工作区的章节集合；章节为空；引用校验的空白与标点容错；回归（无歌词的现有简报用例不变）。
- **完成标准**：无歌词的 `concept` 全部既有测试不变且通过。
- **验证命令**：`make check`。

### T5：`produce` 的歌词支持（完成）

- **目标**：模型在有歌词时拿到范例与规则，预览与校验围着歌词转，成片记录歌词版本。
- **涉及文件**：`backend/src/studio/stages/produce/prepare.py`、`produce/prompt.md`；新增范例 `backend/src/studio/stages/common/scenes/exemplar/lyrics-techniques.js`（常量 `LYRICS_EXEMPLAR` 放在 `common/scenes/__init__.py`）；`engines/render/html/probe.py: reel_sample_times`（加歌词起始采样）；`stages/common/scenes/render_preview_html.py` 与 `validate_scenes_html.py`（带入歌词、警告）；`backend/src/studio/worker_html.py`（`final.json.lyrics_hash`）；测试 `tests/stages/test_produce_*.py`、`tests/engines/…` 的采样用例、`tests/test_worker_html*.py`。
- **接口与要点**：
  - `prepare_turn`：有歌词才拷贝 `lyrics-techniques.js`（到工作区的上游参考位置，与另外两个范例同处）；无歌词不拷，现有「只拷两个范例」的测试不变。
  - 范例内容：字幕条跟随 `env.lyric()` 的 `progress`、关键字随 `env.hit('beat')` 放大、数字滚轮、曲线绘制、终端打字、整屏大字闪出；全部是 `t` 的纯函数；开头说明「不是模板」。体积控制在与现有范例同量级。
  - 提示词：新增歌词章节（设计 §5），写入「不要写死秒数」「每句至少一个画面或关键字」「意象以简报为准」「镜头划分建议跟乐句走」「字幕样式按简报」；不得出现旧词（既有的提示词禁词测试继续生效）。
  - 采样：有歌词时把各句起始时刻并入采样（均匀抽样、去重、仍受 16 张上限），与稀有事件、能量峰值采样合并；无歌词时输出与改动前相同（回归）。
  - 警告：有歌词但所有场景脚本都没引用 `env.lyric`/`env.lyrics` → 警告（不拦）；检查用静态文本匹配即可。
  - `final.json.lyrics_hash`：有歌词时为文件内容的 sha256，无歌词时不写该键（保持无歌词成片的 `final.json` 不变）。
- **测试（先写）**：审查重点 3；有/无歌词的 `prepare_turn`；采样含歌词起始且不超上限；警告出现与消失；`final.json` 有/无该键；提示词关键规则。
- **完成标准**：无歌词的 `produce`、讲解类全部既有测试不变且通过。
- **验证命令**：`make check`。

### T6：前端（完成）

- **目标**：上传区能传歌词，「配乐」标签能看到歌词并跳转。
- **涉及文件**：`frontend/src/features/canvas/music/SourceUploader.vue`（或新增 `LyricsUploader.vue`，歌词上传/更换/删除，只在 `allowUpload` 为真时显示）、`ImportMusicCanvas.vue`、`AnalysisSummary.vue`（或新增 `LyricsList.vue`，每行「时间 + 文字」，点击 `seek`）、`importView.ts`（`.lrc` 白名单与 200 KB 上限，注释注明与后端一致，见 TD-78）、`frontend/src/api/endpoints.ts`、`types/api.ts`（`MusicMetaOut.lyrics`）、`composables/queries.ts`（上传后让 meta 失效）；对应 spec。
- **接口与要点**：
  - 显示条件与歌曲上传区一致：「创意与要求」进行中才可上传/更换/删除；其他阶段只读列表。
  - 没传歌曲时不显示歌词上传（先传歌）；已传歌词显示行数与「更换歌词」「删除歌词」。
  - 歌词列表的当前行跟随播放位置高亮。
  - 能量曲线叠加歌词刻度为**可选小项**：本任务内若不增加复杂度则做，否则记进 TODO，不阻塞验收。
- **测试（先写）**：显示条件（各阶段、有无歌曲、有无歌词）；上传成功/失败提示；列表点击跳转；高亮；`vue-tsc` 与 eslint 干净。
- **完成标准**：既有音乐画布 spec 不变且通过。
- **验证命令**：`make check`。

### T7：文档、真实模型冒烟与 L4（完成）

- **目标**：同步文档，用真实模型与浏览器验证。
- **涉及文件**：`docs/ARCHITECTURE.md`、`docs/glossary.md`（歌词、`LyricLine`、「歌词意象」）、`docs/quality/QUALITY.md`、`docs/references/produce-stage.md`（补实测）、`docs/references/import-music-mv.md`、`docs/plans/TODO.md`；`backend/tests/smoke/test_music_video_smoke.py`（加 `STUDIO_SMOKE_LRC`，缺失则只跑无歌词部分并记录「歌词部分未验证」）。
- **要点**：
  - 冒烟断言：`brief.md` 含「歌词意象」章节；`produce` 的场景脚本引用 `env.lyric`；成片通过；证据里保存每句歌词句首的预览帧路径，供我对照核对。
  - 冒烟用本地 Claude 登录（见 smoke-testing-policy）；耗时与花费如实记录。
  - L4（隔离实例，注意起独立 worker）：上传歌曲与歌词、覆盖、删除、列表跳转、非进行中阶段只读；截图附入验证记录。
- **完成标准**：AC6、AC7；`make check` 绿；计划状态改「待验收」；整分支独立评审并处理发现。

## 进度

- T1 完成（`timeline/lyrics.py`、`LyricLine`、27 个解析测试，`make check` 绿）。
- T2 完成（`Timeline.lyrics` 有类型，`_load_produce_import` 读 `music/lyrics.lrc` 并按 `range` 截取，`runtime.js` 的 `env.lyrics`/`env.lyric()`；7 个时间轴测试 + 3 个真实 Chromium 用例；`make check` 绿，相关 `slow` 用例 31 个通过）。
- T3 完成（`POST/DELETE /music/lyrics`、`MusicMetaOut.lyrics`、`analyze_music` 的 `lyrics_note`、`music/lyrics.lrc` 进 `concept`/`produce` 的托管文件；11 个接口测试 + 3 个概况测试 + 范围与 stale 测试；`make check` 绿）。
- T4 完成（`sections_for`、`check_concept_text(text, lyrics)`、`workspace_lyrics`、提示词、`status_summary`；12 个新测试，`make check` 绿）。
- T5 完成（歌词采样 `_lyric_times`、没引用 `env.lyric` 的警告、`lyrics-techniques.js` 与 `prepare_turn` 条件拷贝、提示词歌词章节、`final.json.lyrics_hash`；新增 12 个测试含真实 Chromium 跑范例；`make check` 绿）。
- T6 完成（`LyricsUploader`、`LyricsList`、`importView` 的 `checkLyricsFile`/`lyricAt`、两个 mutation 与接口、`ImportMusicCanvas` 接入；23 个新前端测试；`make check` 绿）。
- T7 完成（文档同步；MV 带歌词冒烟通过；浏览器 L4 走通，见「验证记录」）。
- 整分支独立评审（2026-10-07）：无阻塞缺陷（25 个导入契约保持）。已修：歌词解析 O(n²) 改线性（24000 行一次解析 < 1 秒，有测试）；损坏歌词文件在界面上可删除（`lyrics_error`）；引用校验归一化并提高短句门槛；前端 `lyricAt` 与运行时 `env.lyric()` 同刻并列规则一致；提示词与文档小问题。登记不修：TD-82（采样优先级）、TD-83（`request.form()` 资源边界）、TD-84（解析与警告的边角）。

## 下一步

- 已验收并合并到 main；真实 LRC 的试听待负责人在使用中确认。

## 决策记录

- D1（2026-10-07）：LRC 解析放在 `timeline`（纯能力层）而不是 `stages`，因为时间轴加载器、上传接口、`concept` 检查都要用，放 `stages` 会被阶段互不 import 的契约卡住。
- D2（2026-10-07）：删除歌词接口做成幂等（不存在也返回成功），前端不需要先判断。
- D3（2026-10-07）：`concept` 的「引用至少一句真实歌词」只做逐字包含（忽略所有空白，含全角），不做模糊匹配；模型引用时改了几个字会被拒绝，错误信息列出歌词开头三句作为例子（没有做「最接近」的模糊搜索）；单字行（如「啊」）在有更长的行时不算引用。
- D4（2026-10-07）：`final.json.lyrics_hash` 取时间轴里（已按截取区间裁剪的）歌词行的规范 JSON 哈希，而不是 `lyrics.lrc` 文件字节的哈希：它描述的是这次渲染真正用到的歌词，不受「读文件之后又被换」影响。
- D5（2026-10-07）：预览歌词采样点取句首后 0.3 秒（短句取中点），每个镜头最多 8 个歌词采样，其余仍由 16 张的总上限收口。

- D6（2026-10-07）：冒烟在没有 `STUDIO_SMOKE_LRC` 时用**自编的占位歌词**跑完整流程（计划原写「缺失则跳过歌词部分」）：为了让机制在真实模型上走一遍；真实歌词的意象质量仍待负责人试听。
- D7（2026-10-07）：评审后新增 `MusicMetaOut.lyrics_error`（歌词文件存在但不可用时的原因），前端据此保留「删除歌词」入口——设计 §6 没写，属于对设计的小补充；`env.lyric()` 的 `i` 是**裁剪后歌词列表**里的序号（设计 §3.3 写「整首歌内的序号」，已批准的设计不改，以此为准）；`check_concept` 的引用校验改为 NFKC + 忽略大小写/标点/空白，少于 4 个字的歌词行只在没有更长的行时才算引用。

## 意外与发现

- 2026-10-07：解析时落在 `[歌曲时长, 时长+1 秒]` 内的句子（如歌曲末尾稍晚的时间戳）不报错，但自身不成为歌词行（`start >= duration` 丢弃），仍作为上一句的结束边界；晚于 `时长+1` 才报错。`[offset:]` 造成的负时间钳到 0，不报错。
- 2026-10-07：`env.lyric()` 同一时刻多句时取开始最晚的，并列取文件里靠前的（双语歌词的第二句要从 `env.lyrics` 里取）；`LYRICS_PATH` 常量放在 `timeline/lyrics.py`（`stages` 可以 import `timeline`），T3 直接复用，不再放 `stages/common/music_source.py`。
- 2026-10-07：歌词上传端点用 `request.form()`（歌词 ≤ 200 KB，不需要像歌曲那样流式解析）；`Content-Length` 超过 400 KB 直接拒绝。meta 里的歌词按整曲秒给（不随 `range` 平移，与 `sections` 一致）；歌曲未分析时没有时长，最后一句取开始后 5 秒。
- 2026-10-07：能量曲线上叠加歌词刻度（T6 的可选小项）没做：列表加点击跳转已够用，刻度要改 `EnergyView` 的坐标层，价值有限，记入 TODO P2。

## 阻塞

- 无

## 验证记录

- 真实模型冒烟（2026-10-07，Claude 本地登录；详见 `docs/references/produce-stage.md`）：MV 带 11 句**自编占位歌词**通过，20 分 36 秒；简报含「歌词意象」，场景脚本引用 `env.lyric`；抽 8 句歌词句首的成片帧核对，字幕、关键字、对应画面都在。真实歌词的意象质量、节拍是否卡准、好不好看**未验证**，等负责人用真实 LRC 试听。
- L4（2026-10-07，内置浏览器，隔离实例）：创意阶段上传 `.lrc` → 「已上传 4 句」与歌词列表，空文本结束标记不显示成歌词；点击行跳到 12 秒并高亮；无时间戳文件显示服务端中文原因，`.txt` 被客户端挡住；删除后列表消失；配乐与动画阶段只有只读列表、没有上传区。创意阶段的上传面板偏窄（靠滚动），已知不处理。
