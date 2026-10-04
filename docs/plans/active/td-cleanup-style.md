# td-cleanup-style：风格库重构后的技术债清理

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 待验收 |
| 里程碑 | 风格库重构之后（整理） |
| 设计依据 | ADR [0019](../../decisions/0019-风格库改用磁盘目录存储.md)；登记表 [tech-debt.md](../../quality/tech-debt.md)；上一份清理计划 [td-cleanup-m4](../completed/td-cleanup-m4.md) |
| 分支 | `td-cleanup-style` |
| 批准记录 | 2026-10-04：负责人要求按我建议的范围安排处理（会让用户丢字或没有反馈的三条前端债、`.cache` 噪音、登记表编号重复）；2026-10-04：负责人批准本计划，要求在本会话内直接执行 |

## 目标

清掉风格库重构评审留下的、用户会直接遇到的小债：编辑时丢字、操作失败没有提示、每轮多出的「已清除：.cache」通知；并把登记表里重复的 TD 编号理顺，让后续引用不再有歧义。完成后 `make check` 为绿。

## 范围

**包含：**

- 登记表编号整理：2026-10-04 风格库评审登记的 8 条（现在也叫 TD-44～TD-51，和 10-02、10-03 的 TD-44～TD-50 撞号）改为 TD-52～TD-59，同步改所有引用。
- 风格库评审 M2（`.cache` 通知噪音）。
- 风格库评审 M4（删文件冲掉防抖中的编辑）、M5（「放弃修改」失败没有提示）、I2 残余（点发送到 busy 之间敲的字被丢弃）。

**不包含：**

- TD-27（sandbox 拒读缺口、`~/.claude/projects`）：安全类，需要真机验证，另排计划。
- 需要真实 API key 的冒烟验证（TD-39、TD-41、TD-47）：会产生费用，SOP §6 第 7 条需事先同意。
- TD-42（其余 8 套旧风格逐个冒烟）、TD-45（时间序列化，公共接口变更需批准）。
- 风格库评审 M1/M3/M6/M7（读不出的文件删不掉、崩溃后草稿不清理、422 逐条显示、`_swap` 毫秒级窗口）：暂无实际症状或影响面小，留在登记表。
- 后端进程被 `kill -9` 后 `claude` 子进程是否变孤儿的实测（需要的话另开一条）。

## 验收标准

- [ ] AC1：登记表没有重复编号；`QUALITY.md`、`style-library.md` 里对风格库评审那 8 条的引用都指向新编号（验证方式：`grep` 逐个核对；`make check` 的文档检查通过）
- [ ] AC2：OpenAI 运行时在草稿里留下 `.cache/` 时，每轮结束静默清除，不再产生「已清除：.cache」通知（验证方式：后端单测）
- [ ] AC3：敲了字之后 600ms 内删除另一个文件，刚敲的字不会被冲回旧内容，并且最终写入服务端（验证方式：`useStyleDraft` 单测；L4 实际操作一次）
- [ ] AC4：「放弃修改」失败（409、网络错误）时界面显示原因，草稿保留；成功路径不变（验证方式：`useStyleDraft`/`StyleEditView` 单测；L4 在 AI 运行中触发 409）
- [ ] AC5：点发送起编辑区就只读，发送失败立即恢复，发送成功则等草稿状态重取、`busy` 为真后由服务端状态接管，中间没有可编辑的空档（验证方式：挂载测试；L4 肉眼确认）
- [ ] AC6：`tech-debt.md`、`QUALITY.md` 已更新，`make check` 为绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：登记表编号整理（完成）

- **目标**：消除 TD 编号重复。
- **涉及文件**：`docs/quality/tech-debt.md`、`docs/quality/QUALITY.md`（frontend 与 styles 行里的「TD-44～TD-51」）、`docs/plans/completed/style-library.md`（进度与评审段落里两处「TD-44～TD-51」）。
- **要点**：只改 10-04 风格库评审登记的 8 条（登记表里「来源」为「风格库重构整分支评审」或「评审 M*」「评审 I2 的残余」的那些行），映射为 TD-44→52、45→53、46→54、47→55、48→56、49→57、50→58、51→59；10-02、10-03 的老条目（以及 `0013-thinking事件.md`、`chat-ui-redesign.md`、`canvas-layout.md` 里的引用）不动。「已处理」表里的 TD-43 是另一条，不动。
- **测试**：文档任务，没有先写失败测试的对象；用脚本检查登记表第一列没有重复编号（可以顺手加进 `scripts/check_docs.py`，作为「文字约定改成机器检查」；只在改动不超过几行时才加，否则登记为新债）。
- **完成标准**：登记表编号唯一；全仓库 `grep "TD-4[4-9]\|TD-5[0-9]"` 的每处引用都指向正确的那一条。
- **验证命令**：`make check`

### T2：`.cache` 加进运行时目录（完成）

- **目标**：AC2。
- **涉及文件**：`backend/src/studio/styles/store.py`（`_RUNTIME_DIRS`，同步更新它下面的说明文字）、`backend/tests/styles/test_store.py`（紧挨现有 `.claude` 用例，约第 485 行）。
- **要点**：`prune_draft` 对 `_RUNTIME_DIRS` 里的目录照常删除但不放进返回值。
- **测试**：先写失败用例：草稿里有 `.cache/tmp/x`，`prune_draft` 之后目录不在、返回列表不含 `.cache`；同时另有一个真多余文件时它仍被报告。
- **完成标准**：用例通过，`.claude` 的既有用例不受影响。
- **验证命令**：`make check`（后端）

### T3：删文件不冲掉编辑；放弃失败要提示（完成）

- **目标**：AC3、AC4。
- **涉及文件**：`frontend/src/composables/queries.ts`（`useDeleteDraftFileMutation`、`useDiscardStyleDraftMutation` 附近）、`frontend/src/features/styles/useStyleDraft.ts`、`useStyleDraft.spec.ts`、`StyleEditView.vue`、`StyleEditView.spec.ts`。
- **接口与要点**：
  - M4：`useDeleteDraftFileMutation.onSuccess` 目前用 `invalidateStyleDraft`，它按前缀把该风格下所有文件内容查询一起失效，正在防抖中的编辑（只在查询缓存里）会被服务端旧内容覆盖。改为只失效草稿状态这一个 key（`queryKeys.styleDraft(id)`，`exact: true`）；被删文件自己的缓存仍由 `removeFile` 里的 `removeQueries` 清掉。
  - M5：`useStyleDraft.discard()` 改为失败时不抛出：返回 `{ wasNew: boolean } | null`，原因写入新增的 `discardError: Ref<string | null>`（沿用 `errorMessage`）；成功时清空它。`StyleEditView.discard()` 收到 `null` 时不发 `discarded` 事件，并把 `discardError` 显示在现有 `data-testid="style-server-error"` 的那一行（与保存错误共用位置，保存错误优先）。`discard` 唯一调用方是 `StyleEditView`。
- **测试**（先写，确认失败）：
  - `useStyleDraft.spec`：先 `edit('STYLE.md', 新文本)`，不等防抖，立刻 `removeFile('references/x.md')`；断言 `STYLE.md` 的缓存文本仍是新文本，且 `flush()` 后假后端收到的是新文本。
  - `useStyleDraft.spec`：假后端让 `discardStyleDraft` 返回 409，断言 `discard()` 返回 `null`、`discardError` 有内容、草稿缓存没有被清掉。
  - `StyleEditView.spec`：同样的 409 下界面出现错误文字、不触发 `discarded`。
- **完成标准**：新用例通过，既有的 `removeFile`/`discard` 用例不变。
- **验证命令**：`make check`；L4 见 T5。

### T4：点发送起本地锁住编辑区（完成）

- **目标**：AC5。
- **涉及文件**：`frontend/src/components/session/SessionPanel.vue`（`onSubmit`、`onContinue`）、`frontend/src/features/styles/StyleChatPane.vue`、`StyleEditView.vue`，及对应 spec。
- **接口与要点**：
  - `SessionPanel` 新增事件 `sending(value: boolean)`：`onSubmit`/`onContinue` 一进来（`beforeSend` 之前）发 `true`，`finally` 里发 `false`；原有的 `sent` 事件保持不变。其他使用方（项目工作台、头脑风暴）不监听即无影响。
  - `StyleChatPane` 转发为自己的 `sending` 事件。发送失败（`sending(false)` 且没有紧跟 `sent`）立即转发 `false`；发送成功时，等 `invalidateStyleDraft` 触发的草稿状态重取完成（此时 `busy` 已为真）后再转发 `false`，避免「本地锁已放开、服务端状态还没到」的空档。
  - `StyleEditView` 用一个本地 `sending` ref，并入 `locked`（提示文案沿用「AI 正在修改，完成后可以继续编辑」）。
  - 切换风格或卸载时本地锁复位。
- **测试**（先写）：`StyleChatPane.spec`——发送开始转发 `sending(true)`；发送失败转发 `false`；发送成功时在草稿重取完成之前不转发 `false`。`StyleEditView.spec`——收到 `sending(true)` 后编辑器与按钮只读，`false` 后恢复。
- **完成标准**：用例通过；`SessionPanel` 的既有测试不变。
- **验证命令**：`make check`

### T5：收尾与 L4（完成）

- **目标**：AC6，并对 AC3～AC5 做真实浏览器走查。
- **涉及文件**：`docs/quality/tech-debt.md`（本计划处理的条目移到「已处理」，写明处理方式）、`docs/quality/QUALITY.md`（`styles`、`frontend` 行的日期与说明）、本计划。
- **L4**（控制者在内置浏览器里做，隔离数据目录 + fake 运行时，不用真实 key）：① 编辑 `STYLE.md` 后 600ms 内删除另一个文件，刷新后内容保留；② 让 fake 运行时在运行中，点「放弃修改」，看到 409 的原因；③ 点发送后立刻尝试敲字，编辑区已只读，AI 轮次结束后恢复。截图放进 `data/evidence/td-cleanup-style/`。
- **完成标准**：AC1～AC6 都有证据；计划状态改为待验收，经负责人验收后移到 `plans/completed/`。
- **验证命令**：`make check`

## 进度

- 2026-10-04 — T1 登记表 8 条改为 TD-52～TD-59，三处引用同步；`check_docs.py` 新增「未处理条目编号唯一」检查（对旧登记表实测报 7 处重复）— `make check` 绿（59e6294）
- 2026-10-04 — T2 `_RUNTIME_DIRS` 加 `.cache`；先写失败用例（`removed` 多出 `.cache`），实现后 `tests/styles` 117 个通过（9d5f5ed）
- 2026-10-04 — T3 `useDeleteDraftFileMutation` 只失效草稿状态（`exact`）；`discard()` 失败返回 `null` 并写 `discardError`，`StyleEditView` 显示；先写 4 个失败用例（含 TD-55 复现：缓存被冲回旧内容），假后端加 `discardError`（1e029ed）
- 2026-10-04 — T4 `SessionPanel` 新增 `sending` 事件（发送与继续都发，`beforeSend` 之前 true、finally false）；`StyleChatPane` 转发，成功时等草稿状态重取完成再发 false，失败或重取出错立即发 false；`StyleEditView` 本地 `sending` 并入 `locked`，换风格复位；每处先写失败用例（db0f4cc）；评审后改为 `accepted` 事件（见决策记录）
- 2026-10-04 — T5 L4 在隔离实例上走查 AC3/AC4/AC5 通过（`data/evidence/td-cleanup-style/l4.md`）；tech-debt.md 把 TD-53/55/56/59 移到已处理，QUALITY.md 同步

## 下一步

- 评审已完成并处理（见「意外与发现」）；状态改「待验收」，等负责人验收，再移到 `completed/` 并合并（SOP §7、§8）。

## 决策记录

- 2026-10-04：执行方式：本项目计划没有 brief 文件，不使用 SDD 脚本，计划文件的「进度」「决策记录」当账本；分支直接建在当前检出（计划文件未跟踪，建 worktree 会丢它）。
- 2026-10-04：T3 `discard()` 失败时除了返回 `null` 和显示原因，还把清掉的防抖编辑重新排上（`edit()` 重放）。计划只要求「草稿保留」，但原实现在请求前就清空了待写入编辑，失败后这些字会静默丢失，和 TD-55 同类。代价：多一个用例，失败后若服务端仍 busy，重放的写入会再被 409 丢弃（走既有的 409 路径）。
- 2026-10-04：T4 `onContinue` 成功后也发 `sent`——**此裁定已被整分支评审推翻**（Important）：工作台监听 `sent`，会把预填的回退建议标成已处理，而 [继续] 并没有把它发出去。改为 `sent` 只在发新消息时发（恢复原行为），新增 `accepted` 事件（发送和继续都发），风格对话区改听 `accepted` 来等草稿状态重取。
- 2026-10-04：新编号用 TD-52～TD-59，不去动老的 TD-44～TD-50。理由：老编号已被 `chat-ui-redesign`、`canvas-layout`、ADR 0013 等多处引用，而新那批只被 `QUALITY.md` 和 `style-library.md` 两个文件引用，改动面最小。

## 意外与发现

- 整分支评审（Opus 新上下文，只读）：1 条 Important 已修（I1，`sent`/`accepted`，先写失败用例）；Minor 登记为 TD-60～TD-63：发送后等重取可能被 SSE 的重取打断、两次发送重叠时布尔锁提前放开（TD-60）、放弃失败后重放会覆盖请求期间新敲的字（TD-61）、`discardError` 只在下次点放弃时清空（TD-62）、编号唯一检查不看已处理表且正则对空格严格（TD-63）。评审指出的测试问题（「重取失败也要解锁」模拟了真实 `invalidateQueries` 不会出现的 reject、换风格复位用例在生产里因 key 走不到）留着，无害。
- T1：登记表「已处理」里 TD-25/27/39 各有「部分」条目，和未处理表同号，是有意的拆分；新检查只看「已处理」之前的未处理条目。

## 阻塞

- 无

## 验证记录

- AC1：`python3 scripts/check_docs.py` 通过；新检查对旧登记表（`git show HEAD~4:...`）报 7 处重复，对现在的登记表通过；`grep` 核对 `QUALITY.md`、`style-library.md` 的引用已指向 TD-52～TD-59。
- AC2：`backend/tests/styles/test_store.py::TestPruneDraft::test_the_openai_shell_cache_directory_is_removed_silently`（先失败：`removed` 多出 `.cache`；实现后通过）。
- AC3/AC4/AC5：单测见 `useStyleDraft.spec.ts`（删文件不冲掉编辑、放弃失败、失败后编辑不丢）、`StyleEditView.spec.ts`、`StyleChatPane.spec.ts`、`SessionPanel.spec.ts`，均先见失败；L4 见 `data/evidence/td-cleanup-style/l4.md`。
- AC6：`make check` 绿（2026-10-04，T4 之后：后端 1592、前端 901）。
