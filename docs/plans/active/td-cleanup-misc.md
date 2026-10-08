# td-cleanup-misc：第二批技术债清理（后端小项 + 前端小瑕疵）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | td-cleanup-music 之后（整理） |
| 设计依据 | 登记表 [tech-debt.md](../../quality/tech-debt.md) 的 TD-54、58、84（①②）、72、74、68、69（②④）、70、62、67、49 |
| 分支 | `td-cleanup-misc`（从 `td-cleanup-music` 分出，叠在它上面；前一个分支合并前，这个分支包含它的全部提交） |
| 批准记录 | 2026-10-08：负责人选定范围「后端小项加前端小瑕疵」，并同意叠在 td-cleanup-music 上；负责人批准计划，用 native 方式执行 |

## 目标

把登记表里改动单点、不涉及公共接口与设计取舍的条目清掉：崩溃恢复的两处残留、歌词解析的两处边角、两处重复代码、渲染引擎的几处小缺口、后端与前端的测试缺口，以及前端的一批小瑕疵。

## 范围

**包含：** TD-54、TD-58、TD-84 的①②、TD-72、TD-74、TD-68、TD-69 的②④、TD-70 的①②、TD-62、TD-67、TD-49 的①–⑦。

**不包含（原因）：**

- TD-84 ③（同一时刻既有歌词又有结束标记时结束标记不生效）：期望行为不明确，需要先定语义，不是机械修复。
- TD-84 ④⑤：④ 涉及两处时长来源的口径，⑤ 是静态正则的取舍，保持登记。
- TD-69 ①（JS 词法扫描）、③（按设计加长镜头再测敏感度）：需要设计取舍，保持登记。
- TD-57、TD-78：要改接口返回形状（detail 字符串变列表／由接口下发上限），属公共接口变更，需单独批准。
- TD-60、TD-61：前端竞态，细微且需要精细复现，不是机械修复。
- TD-46、TD-48、TD-82、TD-77、TD-79、TD-66 等：涉及展示功能取舍或较大改动。
- TD-45：改公共接口，等单独批准。

**开工前提醒：** 登记表里的描述是登记当时的判断。每个任务开工先读登记表原文，再读对应代码确认现状；如果某条的前提已经不成立（像 TD-50 那样），不要硬改，在计划的「意外与发现」里写明并按"过时"关闭。

## 验收标准

- [ ] AC1：进程崩溃时风格轮次正在运行，重启恢复会清理草稿里的多余文件和符号链接；`_swap` 在两次 rename 之间被杀留下的 `.<id>.old-*` 会在启动时还原（验证方式：恢复流程与 store 的新测试）
- [ ] AC2：4 位小数时间戳的歌词行不再被静默忽略；晚于「时长 + 1 秒」的条目只丢弃那一行，不再拒绝整个文件（验证方式：`timeline/lyrics.py` 的新测试，含上传端点一条）
- [ ] AC3：`song_job` 不再导入 runner 的私有函数；`imported.py` 与 `build.py` 共用同一份常量与辅助函数；两处行为不变（验证方式：既有测试不改即通过）
- [ ] AC4：成片缓存键包含随包字体与编码参数；脚本与镜头的符号链接被拒绝；派生文件只读且重新准备仍能覆盖（验证方式：新测试）
- [ ] AC5：登记表 TD-68 的三处后端测试缺口补上，`prepare_turn` 异常不再丢失原异常类型（验证方式：新测试）
- [ ] AC6：前端 TD-62、TD-67、TD-70②、TD-49 的七处各有对应测试或明确的验证方式，浏览器里实测的结论写进验证记录（验证方式：`vitest` + 在浏览器里实际点一遍）
- [ ] AC7：`tech-debt.md` 更新（处理完的移到已处理、过时的按过时关闭），`make check` 为绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：崩溃恢复的两处残留（完成）

- **目标**：TD-54、TD-58。
- **涉及文件**：`backend/src/studio/agent/recovery.py`、`backend/src/studio/styles/store.py`（`_swap`、`prune_draft`）、启动入口（`main.py` lifespan 里调用恢复处）、对应测试。
- **接口与要点**：
  - TD-54：`recover_on_startup` 对 `subject_id` 非空（风格会话）的会话，在收尾 running 的 turn 后调用 `prune_draft`；不改 `prune_draft` 本身。
  - TD-58：新增一个启动期函数（放在 `styles/store.py`，名字如 `recover_interrupted_swaps(data_dir)`）：扫描风格库目录下的 `.<id>.old-*`，若对应正式目录 `<id>` 缺失则把它改名还原，若正式目录存在则删除这份旧备份；`.tmp-*` 残留一并清掉。在 `main.py` 的 lifespan 启动时调用。
- **测试（先写）**：① 模拟崩溃：草稿里放符号链接与多余文件、会话挂着 running 的风格轮次，调用恢复后草稿合法、保存不再 422；② 正式目录缺失、`.old-*` 存在 → 还原；正式目录存在 → 旧备份被清掉；无关目录不动；③ 恢复函数可重复调用。
- **完成标准**：以上测试通过。
- **验证命令**：`make check`

### T2：歌词解析的两处边角（完成）

- **目标**：TD-84 ①②。
- **涉及文件**：`backend/src/studio/timeline/lyrics.py`（`_STAMP`、`parse_lrc`）、`backend/src/studio/api/music_import.py` 的歌词端点相关测试。
- **接口与要点**：① `_STAMP` 的小数部分放宽到常见写法（1–6 位），`_seconds` 的 `float(f"0.{fraction}")` 无需改；② 超出「时长 + 容差」的条目只丢弃，不再进入 `problems` 导致整份文件被拒；全部条目都被丢弃（没有任何歌词）时仍报"至少要有一句歌词"。`LyricsError` 的构造与文案其余部分不变。上传端点与时间轴加载两处共用这个解析函数，不需要分别改。
- **测试（先写）**：4 位小数 `[00:12.3456]` 被识别；晚于时长的一行被丢弃而其余行保留；全部晚于时长 → 仍报错；既有测试不改即通过。
- **完成标准**：以上测试通过。
- **验证命令**：`make check`

### T3：两处重复代码整理（完成）

- **目标**：TD-72、TD-74，纯重构，不改行为。
- **涉及文件**：`backend/src/studio/engines/audio/runner.py`、`song_job.py`；`backend/src/studio/timeline/imported.py`、`build.py`；`docs/ARCHITECTURE.md`（若新增模块）。
- **接口与要点**：
  - TD-72：把 `_drain`、`_kill_group`、`_tail_lines` 在 runner 里改为公开名字（或抽到 `engines/audio` 内一个共用小模块），`song_job` 改用公开名；把 `TMPDIR` 指向输出目录的约定写进 runner 的文档字符串。
  - TD-74：把 `imported.py` 复制的网格／容差／取整常量与辅助函数抽到 `timeline` 内部共用模块，两处引用；先逐项对照确认两份实现完全相同，不同的地方保留原样并在报告里说明。
- **测试**：既有测试不改即通过；若发现两份实现有差异，补一条钉住当前行为的测试。
- **完成标准**：`grep` 不再有跨模块导入下划线开头的名字；重复的常量只剩一份。
- **验证命令**：`make check`

### T4：渲染引擎的几处小缺口（完成）

- **目标**：TD-69 ②④、TD-70 ①。
- **涉及文件**：`backend/src/studio/engines/render/html/static_check.py`、`probe.py`、`prepare` 相关模块（`prepare_turn` 所在处，先 grep 确认）、`worker_html.py: _cache_key`、对应测试。
- **接口与要点**：
  - TD-69 ②：镜头与 `lib` 脚本同样做符号链接／越界检查（参照现有对其他文件的检查方式）。
  - TD-69 ④：`prepare_turn` 物化的派生文件设为只读（0444）；重新准备时要能覆盖（先 `unlink` 或先改回可写再写）。不处理"阶段改写已物化文件"那一半（登记表里说的 `derived_upstream`），保持登记。
  - TD-70 ①：缓存键纳入 `FONTS_DIR` 下字体文件的内容摘要与编码参数，不再靠人工 bump `ENGINE_VERSION` 一项。摘要计算要缓存（进程内只算一次），避免每次渲染都读字体。
- **测试（先写）**：符号链接镜头被拒；派生文件权限为只读且二次准备成功；改动字体字节或编码参数 → 缓存键变化，未改动 → 不变。
- **完成标准**：以上测试通过。
- **验证命令**：`make check`

### T5：后端测试缺口（待开始）

- **目标**：TD-68 ①②③。
- **涉及文件**：`backend/tests/db/`（迁移）、`backend/tests/agent/`（前言、runner）、`backend/src/studio/agent/runner.py` 或 `turn_state.py`（`prepare_turn` 异常包装处，先 grep）。
- **接口与要点**：① 0008→0009 迁移后再定稿／生成前言的端到端测试；② 前言对未注册上游回退到 `[name]` 的分支；③ `prepare_turn` 抛异常被包成 `RuntimeError` 丢失原类型：改成 `raise ... from exc`，并在消息里带原异常类型名。
- **测试**：先写①②③的测试，③ 在改动前应失败（断言 `__cause__` 与消息里的类型名）。
- **完成标准**：三处缺口都有测试。
- **验证命令**：`make check`

### T6：风格编辑的两处小事与前端测试缺口（待开始）

- **目标**：TD-62、TD-67、TD-70②。
- **涉及文件**：`frontend/src/features/styles/useStyleDraft.ts`、`StyleEditView.vue`、`frontend/src/components/VideoKindPicker.vue`、`features/ideas/CreateProjectDialog.vue` 及 spec、HTML 预览组件 `HtmlPreviewPane.vue`。
- **接口与要点**：TD-62 在编辑、保存、轮次结束时清掉 `discardError`；TD-67 ① 补不可用组合时提交按钮禁用的挂载测试、② 整理夹具类型转换、③ `canSubmit` 同时要求类型数据可用；TD-70 ② 预览组件由 `v-if` 改 `v-show`（或等价方式），切回"实时预览"标签不再重取整页，注意隐藏时不应继续占用轮询／订阅。
- **测试（先写）**：TD-62 错误提示随编辑消失；TD-67 三条；TD-70 ② 切换标签不重新发请求。
- **完成标准**：以上测试通过；TD-70 ② 在浏览器里实测切换标签的网络请求。
- **验证命令**：`make check`

### T7：快照栏与画布的七处小瑕疵（待开始）

- **目标**：TD-49 ①–⑦。
- **涉及文件**：`frontend/src/features/workbench/SnapshotRail.vue`、`SnapshotDetail.vue`、`SnapshotTimeline.vue` 及 spec、`features/canvas/topic/TopicCanvas.vue`、`EditModeToggle.vue`、`briefStatus.ts`。
- **接口与要点**（逐条见登记表原文的建议处理方式）：① 窄屏隐藏「收起」按钮；② 双选对比无差异时文案区分单选／双选；③ `SnapshotTimeline.spec` 的"不残留旧 diff"先造出一份旧 diff；④ 检查查询失败时区分 `isError`，不再一直转圈；⑤ `brief.md` 不存在或加载中时禁用编辑切换；⑥ agent 运行中那个可聚焦的包装元素加 `role="button" aria-disabled aria-label`；⑦ 折叠再展开时保留选中的快照（选择状态上移到 `SnapshotRail`，或改 `v-show`，二选一，选改动小的）。
- **测试（先写）**：每条一个失败的测试（⑥ 用可访问性查询）；③ 本身就是修测试，先确认旧测试确实没有造出旧 diff。
- **完成标准**：七条都有测试；在浏览器里实际操作窄屏收起、折叠展开保留选中、检查失败状态（可拦截请求制造失败），截图或文字结论写进验证记录。
- **验证命令**：`make check`

### T8：收尾——登记表与计划（待开始）

- **目标**：文档与实际一致。
- **涉及文件**：`docs/quality/tech-debt.md`、`docs/ARCHITECTURE.md`（若有新模块）、本计划。
- **要点**：处理完的条目从未处理表删除，在"已处理"表追加整号行；只处理了一部分的条目（TD-84、TD-69、TD-70）保留未处理行并改写成剩余部分，已处理表里用"TD-n（部分）"行记录这次做的（注意 T5 加的撞号检查：整号不能同时出现在两个表里）；按"过时"关闭的条目写明原因。
- **验证命令**：`make check`

## 进度

- 2026-10-08 — T1 完成：恢复流程补做风格草稿清理（TD-54），启动时还原被打断的 `_swap`（TD-58），`make check` 全绿
- 2026-10-08 — T2 完成：时间戳小数位放宽到 1–6 位，晚于时长的条目只丢那一行（TD-84 ①②）；`make check` 全绿
- 2026-10-08 — T3 完成：runner 的 `drain`/`kill_group`/`tail_lines` 改为公开，`timeline/numeric.py` 收拢 `build`/`imported` 共用的常量与 `is_finite_number`；`make check` 全绿
- 2026-10-08 — T4 完成：缓存键纳入编码参数（`encode_signature`）；镜头／`lib`／`global.js` 链接到工作区外时被静态检查报告、装配与哈希跳过、`_scene_sources` 拒绝；`prepare_turn` 的派生文件设只读（`seal_derived_upstream`）；`make check` 全绿

## 下一步

- 从 T5 开始：读登记表 TD-68 原文；先 grep 迁移测试（`tests/db`）、`agent/preamble.py` 的 `[name]` 回退分支与 `prepare_turn` 异常被包成 `RuntimeError` 的位置（`agent/runner.py` 约第 357 行），先写失败测试。

## 决策记录

- 2026-10-08 — T2：既有测试 `test_invalid_input_is_rejected_with_a_reason` 与 `test_bad_files_are_422...` 里"一行晚于时长就整份拒绝"的用例按 TD-84 ② 的要求改为"只有晚于时长的条目才报错（文案含"晚于歌曲时长"）"。
- 2026-10-08 — 计划范围按负责人选择的「后端小项加前端小瑕疵」，并剔除了需要设计取舍或改公共接口的子项（见「不包含」），理由是这批的价值在于机械、可验证、风险低。
- 2026-10-08 — 分支叠在未合并的 td-cleanup-music 上；`active/` 里暂时有两份计划，文档检查只给出警告。

## 意外与发现

- T4：TD-70 ① 的"字体不在缓存键里"已过时：随包字体经 `page.routes` 的文件字节早就进了 `_cache_key`（页面模板在 `page.html` 里也在）；真正缺的只有编码参数，已补。同时新增的字体用例作为现状的钉子（它一开始就通过，属预期）。
- T4：TD-69 ④ 做成通用的 `seal_derived_upstream`（runner 在 `derived_upstream` 之后调用），而不是改各阶段的 `prepare_turn`；下一轮／轮末的 `materialize_upstream` 本来就先恢复写权限再清空，所以无需改覆盖逻辑。TD-69 ② 采用与资产相同的口径：只拒绝指向工作区外的链接，工作区内的链接仍可用。
- T3：`build.py` 与 `imported.py` 里重复的只有 `BEATS_PER_BAR`、`EPSILON`、有限数判断三项，实现逐字相同；`_TOLERANCE` 等其余常量并没有被复制。`agent/shell.py` 另有一个同名 `_kill_group`，`engines` 不能 import `agent`，保持不动。

## 阻塞

- 无

## 验证记录

- 无
