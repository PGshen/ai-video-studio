# canvas-layout：画布区域布局优化（可拖宽、状态图标化、快照栏）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 进行中 |
| 里程碑 | M5 之后的独立改动（无里程碑编号） |
| 设计依据 | 2026-10-02 对话中的设计（本计划「设计」一节）；纯前端布局改动，不改后端、不改接口，与 [架构设计](../../design/2026-09-26-architecture.md) 无冲突 |
| 分支 | `canvas-layout` |
| 批准记录 | 2026-10-02：负责人确认设计（快照栏默认折叠、独立第三张卡片、悬停气泡含明细）；2026-10-02：负责人批准计划，执行方式为当前会话内联 |

> **执行方式**：当前会话内联（2026-10-02 负责人指定）。

## 目标

让工作台画布区域更紧凑：对话与画布的宽度可拖动调节；去掉「画布」标题行；选题画布的检查结果改成状态图标，并与「渲染/编辑」切换一起放在「简报、笔记」标签行右侧；快照时间线改成右侧可折叠的垂直栏，上面是时间线、下面是所选节点的详情。

## 设计

**页面布局（`ProjectWorkbenchPage`）**

- lg 以上：左侧导航竖栏不变；其右用 reka-ui 的 `SplitterGroup`（水平，已是依赖，不新增包）放三个面板：**对话 | 画布 | 快照栏**，面板之间是可拖的分隔条（键盘可调）。各面板设最小宽度，防止拖到不可用。
- 面板宽度用 `autoSaveId` 记在 localStorage；快照栏是 `collapsible` 面板，折叠状态单独记（`workbench-snapshots-collapsed`，**默认折叠**，首次访问为折叠）；折叠后只剩窄条（图标 + 快照数），再展开恢复上次宽度。
- 画布卡片去掉 `CardHeader`（「画布」标题行）；快照栏是**独立的第三张 Card**，不放进画布卡片。
- 窄屏（< lg）：不用分隔条，对话 / 画布 / 快照栏上下堆叠，快照栏始终展开（沿用现有窄屏策略）。

**快照栏（`SnapshotTimeline`，上下布局）**

- 上：时间线，最新在前，每项显示原因、turn、时间，点选；去掉 `max-h-40`，在栏高度内滚动。
- 下：所选节点详情——标题与时间、「回滚到此」（二次确认；agent 运行时禁用，规则不变）、变更文件列表与 diff。
- 选择规则：选 1 个 → 对比它与**上一个**快照；选 2 个 → 对比这两个（现有对比能力不丢，沿用 `toggleSnapshotSelection` 最多选两个）；选中最早的快照 → 显示「初始快照，没有更早的版本可对比」；没选 → 提示「选择一个快照查看详情」。
- 文件拆分：时间线列表留在 `SnapshotTimeline.vue`；详情（diff 查询、回滚确认弹窗）拆到新的 `SnapshotDetail.vue`，每个 `.vue` 约 250 行以内。

**选题画布（`TopicCanvas` / `MarkdownFilePane`）**

- 检查条 `BriefCheckBar` 换成状态图标 `BriefStatusIcon`：`ok` 绿勾、`warnings` 黄三角、`errors` 红叉圆、`unknown` 转圈；悬停/聚焦弹出气泡（项目已有 `components/ui/tooltip`），内容 = 现在的 `headline` + 错误列表 + 警告列表；图标带 `aria-label`（headline）。
- 「渲染 / 编辑」做成图标分段按钮 `EditModeToggle`，与状态图标一起右对齐放在「简报、笔记（n）」那一行。
- 编辑模式状态从 `MarkdownFilePane` 提到 `TopicCanvas`（`v-model:mode`），简报与当前笔记共用这一个切换；`MarkdownFilePane` 仍负责「文件变化 / 换文件时回到渲染、agent 运行时退出编辑」并通过 `update:mode` 通知父组件。
- agent 运行中：编辑按钮置灰，其 tooltip 写「agent 运行中，只读」；原来那行「只读：agent 正在运行」删除。冲突提示条、保存按钮、保存错误留在内容区不变。
- 其他阶段画布（叙事 / 动画 / 通用文件）内部不动，只随页面布局变化。

## 范围

**包含：** 上述页面布局、快照栏、选题画布三块改动；对应的纯函数、组件测试；L4 浏览器走查；文档与计划更新。

**不包含：** 后端与 API；其他阶段画布的内部重排；快照栏内部的宽度单独拖动（它作为面板，宽度靠分隔条）；diff 渲染方式（继续用 `CodeBlock` 的 `diff` 语言）；左侧导航竖栏。

## 全局约束

每个任务都隐含满足：

- 红线（AGENTS.md）：不改 `../ai-video`；不用 `skip`/`xfail`/`# type: ignore`/`noqa` 绕过失败；不引入计划外的新依赖（`reka-ui`、`@vueuse/core`、`@lucide/vue` 已在 `frontend/package.json`）；不改 `docs/design/2026-09-26-architecture.md`。
- 测试先行：每个任务先写失败的测试并确认失败，再实现。
- 前端遵守 `eslint.config.ts` 的分层规则（`features/*` 之间不互相 import；`components/ui/*`、`ai-elements/*` 为生成代码，不为本计划改动）；单个 `.vue` 约 250 行以内；纯逻辑放 `.ts` 并配 `.spec.ts`。
- 面向用户的文案用中文，代码标识符与注释用英文；提交格式 `<type>(<scope>): <中文说明>`；代码与计划更新放同一个 commit。
- 每个任务结束时 `make check` 为绿。
- L4 在隔离数据目录和 8001/5174 端口上做，不碰负责人正在运行的 8000/5173 实例与真实数据（见 `docs/runbooks/verification.md`）。

## 验收标准

- [x] AC1：页面不再有「画布」标题行；lg 以上对话、画布、快照栏三栏由分隔条分开，拖动可改宽度，刷新后保持；设最小宽度。（验证：L4 拖动截图 + 组件测试）
- [x] AC2：快照栏是独立的第三张卡片，首次访问默认折叠，折叠后窄条显示图标与快照数；展开/折叠状态与宽度刷新后保持。（验证：组件测试 + L4）
- [x] AC3：窄屏（< lg）无分隔条，三块上下堆叠，快照栏展开可用。（验证：L4 窄屏截图）
- [x] AC4：快照栏上下布局；单选对比上一个快照、双选对比两者、选最早快照提示「初始快照」、未选有提示；「回滚到此」仍二次确认且 agent 运行中禁用。（验证：`snapshotSelection.spec.ts`、`SnapshotTimeline`/`SnapshotDetail` 组件测试）
- [x] AC5：选题画布无检查条；状态图标按 `unknown/ok/warnings/errors` 显示，悬停与键盘聚焦都弹出含 headline + 错误 + 警告的气泡，有 `aria-label`。（验证：`BriefStatusIcon` 组件测试 + L4）
- [x] AC6：状态图标与渲染/编辑图标切换右对齐在「简报、笔记」行；简报与笔记共用切换；agent 运行时编辑置灰且气泡说明；换文件/换标签回到渲染。（验证：`TopicCanvas`/`MarkdownFilePane` 组件测试 + L4）
- [x] AC7：文档与计划已更新；`make check` 全绿；收尾清单（SOP §7）完成。

## 评审关注点

设计没有明说、但使用者很可能遇到的情况；每条都在对应任务里有测试。

1. 快照列表为空、只有一个快照、选中的快照 id 在回滚/新快照后已不在列表里：详情区显示提示，不报错、不残留旧 diff（T1）。
2. 分隔条拖到极端、窗口缩放、快照栏折叠后再展开：对话与画布不被压到不可用，展开恢复上次宽度（T3）。
3. 状态图标的键盘可达与屏幕阅读器：Tab 聚焦即弹气泡，`aria-label` 给出结论；检查结果尚未返回（`unknown`）时不显示错误气泡内容（T2）。
4. 编辑中途 agent 开始运行 / 切换笔记 / 切换简报与笔记标签：提升到父组件后的 `mode` 仍会回到渲染，未保存的编辑不被静默带到另一份文件（T2）。
5. 叙事、动画、通用文件画布在去掉标题行、改成三栏后高度与滚动正常，没有双滚动条或内容被截断（T3）。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：快照栏——选择规则与上下布局（完成）

- **目标**：快照栏的选择规则支持单选对比上一个；组件改为上（时间线）下（详情）布局，回滚逻辑原样保留。
- **涉及文件**：
  - 修改 `frontend/src/features/workbench/snapshotSelection.ts`（及 `.spec.ts`）：保留 `computeDiffParams`（两个时）并新增单选语义——新增纯函数（建议名 `resolveDiffTarget(snapshots, selected)`，返回 `none | initial | diff{from,to}`）。
  - 修改 `frontend/src/features/workbench/SnapshotTimeline.vue`：时间线 + 选择状态；去掉 `max-h-40`；栏内滚动。
  - 新增 `frontend/src/features/workbench/SnapshotDetail.vue`：标题与时间、回滚按钮与确认弹窗（`pendingRollbackId` 的非响应式写法与注释原样迁移）、变更文件与 diff。
  - 新增 `SnapshotTimeline.spec.ts` / `SnapshotDetail.spec.ts`（沿用仓库里其他组件测试对 TanStack Query 的 mock 方式）。
- **接口**：`SnapshotTimeline` props 不变（`projectId`、`busy`）；`SnapshotDetail` props：`projectId`、`busy`、`snapshots`（最新在前）、`selected: string[]`。
- **验收标准**：AC4；评审关注点 1。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/workbench`；任务结束 `make check`。

### T2：选题画布——状态图标与编辑切换上移（完成）

- **目标**：检查条变状态图标，图标与渲染/编辑切换一起右对齐在标签行；模式状态提到 `TopicCanvas`。
- **涉及文件**：
  - 新增 `frontend/src/features/canvas/topic/BriefStatusIcon.vue`（替换并删除 `BriefCheckBar.vue`；复用 `computeBriefStatus`，必要时在 `briefStatus.ts` 里补「级别 → 图标/颜色」的纯映射并配 spec）。
  - 新增 `frontend/src/features/canvas/topic/EditModeToggle.vue`（图标分段按钮，`busy` 时编辑置灰 + tooltip）。
  - 修改 `TopicCanvas.vue`（标签行布局、持有 `mode`）、`MarkdownFilePane.vue`（`v-model:mode`，删「只读：…」提示行与自带的切换条）。
  - 新增/更新对应 `.spec.ts`。
- **接口**：`MarkdownFilePane` 新增 `mode: 'view' | 'edit'` prop 与 `update:mode` 事件；其余 props 不变。
- **验收标准**：AC5、AC6；评审关注点 3、4。
- **验证命令**：`cd frontend && pnpm exec vitest run src/features/canvas/topic`；任务结束 `make check`。

### T3：页面三栏布局、可拖宽与折叠快照栏（完成）

- **目标**：`ProjectWorkbenchPage` 改成 对话 | 画布 | 快照栏 三个 `SplitterPanel`，去掉画布标题行，快照栏独立 Card 且默认折叠。
- **涉及文件**：
  - 修改 `frontend/src/pages/ProjectWorkbenchPage.vue`（若超过 250 行，把三栏壳拆成新组件，例如 `features/workbench/WorkbenchSplit.vue`）。
  - 折叠状态与窄屏判断用 `useLocalStorage` / `useMediaQuery`（沿用现有左侧竖栏的做法）；折叠态窄条显示图标与快照数（数量来自 `useSnapshotsQuery`，与 `SnapshotTimeline` 共用缓存）。
  - 先做一个小的可行性检查：reka-ui `SplitterGroup` 在 jsdom 下是否需要 `ResizeObserver` 等 mock；需要则放在测试 setup 里，不改被测代码。
  - 组件测试：折叠默认值与记忆、窄屏不渲染分隔条、画布不再有标题。
- **验收标准**：AC1、AC2、AC3；评审关注点 2、5。
- **验证命令**：`cd frontend && pnpm exec vitest run src/pages src/features/workbench`；任务结束 `make check`。

### T4：L4 走查与收尾（完成）

- **目标**：浏览器里实测拖动、折叠、状态图标气泡、编辑切换、快照详情与窄屏；文档与计划收尾。
- **步骤**：
  - 在隔离端口（8001/5174，隔离数据目录，临时改 `.claude/launch.json` 后恢复）起实例，用演示脚本与几次手动编辑造出多个快照；逐项截图存证到 `data/evidence/canvas-layout/`（git 忽略）。
  - 实际拖动分隔条、刷新确认宽度与折叠状态保持；窗口缩到窄屏；四种检查状态的图标与气泡；叙事 / 动画 / 通用文件三个阶段各看一眼高度与滚动。
  - 更新 `docs/ARCHITECTURE.md`（若提及工作台布局）、`docs/quality/QUALITY.md`；发现的问题按 SOP 登记或修复；填写验证记录；最后一次 `make check`。
  - 若有独立评审，由负责人指定；否则注明自审。
- **验收标准**：AC1–AC7。
- **验证命令**：`make check`。

## 进度

<!-- 每完成一步追加一行：日期 — 任务 — 结果（commit 短哈希） -->

- 2026-10-02 — T1 — `resolveDiffTarget`（单选对比上一个/initial/双选）、`formatSnapshotTime`；`SnapshotTimeline` 改为上时间线下详情，详情与回滚确认拆到 `SnapshotDetail`；前端 `features/workbench` 44 个用例通过
- 2026-10-02 — T2 — `BriefStatusIcon`（四级图标 + 悬停/聚焦气泡）替换并删除 `BriefCheckBar`；`EditModeToggle` 图标分段按钮；`TopicCanvas` 持有模式并右对齐放进标签行，`MarkdownFilePane` 改 `v-model:mode` 并去掉自带切换条与「只读」提示；新增 `src/test/setup.ts`（`ResizeObserver` 桩）；`features/canvas/topic` 21 个用例通过
- 2026-10-02 — T3 — `WorkbenchSplit`（`SplitterGroup` 三面板 + 两个分隔条，窄屏堆叠）、`SnapshotRail`（独立卡片，折叠窄条显示图标与快照数）；页面去掉画布标题行；`features/workbench` 51 个用例通过；隔离实例 L4：三栏、拖宽、刷新后宽度与展开状态保持、折叠/展开、详情区、状态图标气泡、窄屏堆叠、动画阶段画布都走查过
- 2026-10-02 — T4 — 文档（ARCHITECTURE、QUALITY）更新、验证记录填写
- 2026-10-02 — 独立评审（最强模型，全新上下文）+ 修复 — 0 Critical、3 Important、8 条 Minor（见 TD-49）；已修复：窄屏改为纯 CSS 堆叠（跨断点不再重挂载，实测草稿保留）、面板约束改像素（对话 ≥280px、画布 ≥320px、折叠窄条 44px、快照栏展开 ≥240px）、折叠/展开/刷新保持的真实测试；前端 `WorkbenchSplit` 6 个用例

## 下一步

- 待负责人验收；验收后移到 `plans/completed/`（状态「已完成」）并决定是否合并 `canvas-layout`。

## 决策记录

<!-- 执行中自行做出的决定：日期 — 决定 — 理由。影响范围超出本计划的，另写 ADR 并在这里链接。 -->

- 2026-10-02 — 用 reka-ui `SplitterGroup` 而不是自写拖拽 — 已是依赖、带键盘与无障碍支持、自带 `autoSaveId` 持久化，不新增依赖。
- 2026-10-02 — 快照栏做成第三个 `SplitterPanel`（独立 Card），而不是画布卡片内部的子栏 — 宽度同样可拖，且与设计确认一致。
- 2026-10-02 — 快照栏默认折叠（负责人确认）；折叠窄条显示图标与快照数，保证能被发现。
- 2026-10-02 — 单选对比上一个快照、双选对比两者，保留原有对比能力。
- 2026-10-02 — T1：「回滚到此」只在详情区、且恰好选中一个快照时出现，选两个（对比模式）时不出现 — 对比模式下回滚目标有歧义；代价：要回滚到某个快照需先单选它（原来每行都有按钮）。
- 2026-10-02 — T1：时间线每项的时间用新增的 `formatSnapshotTime`（本地 `MM-DD HH:mm`，按 UTC 解析无时区后缀的服务器时间）代替原始 ISO 串 — 窄栏里 26 位时间戳会折行，且原先在东八区差 8 小时（TD-45 同源）；代价：不再显示秒与毫秒。
- 2026-10-02 — T3：折叠状态不另存 `workbench-snapshots-collapsed`，直接用 `SplitterGroup` 的 `autoSaveId` 存下来的布局（快照栏面板尺寸 = 折叠尺寸即折叠）— 一份状态，不会两处不一致；代价：改面板约束（最小宽度等）会让已保存布局失效、回到默认（折叠）。
- 2026-10-02 — 评审后：面板约束全部改用 `size-unit="px"`（对话最小 280、画布最小 320、快照栏折叠 44 / 展开最小 240；对话与画布不设默认值，平分剩余宽度）— 取代 T3 当时「全用百分比」的裁定（评审指出小窗口里 25% 只有约 136px、4% 的窄条比自己的按钮还窄；reka-ui 本身支持 px，L4 在 1100/1300px 实测通过）；代价：1100px 左右三个最小宽度之和超过可用宽度，约束放不下时画布略小于 320px。
- 2026-10-02 — T3：窄屏堆叠时给左侧竖栏加 `max-lg:min-h-max`（网格行不被 `min-h-0` 压成 13px，L4 窄屏发现重叠）。评审后：窄屏不再另渲染一棵树，而是同一个 `SplitterGroup` 用 `max-lg:` 样式改成纵向、隐藏分隔条、覆盖面板内联的 flex 尺寸（`shrink-0!`/`grow-0!`/`basis-auto!`）— 取代「跨断点重新挂载可接受」的裁定（评审指出会静默丢掉画布未保存的编辑和输入框草稿）。
- 2026-10-02 — T2：vitest 加 `setupFiles: src/test/setup.ts`，给 jsdom 补一个空的 `ResizeObserver` 桩 — reka-ui 的 Tooltip（以及 T3 的 Splitter）挂载就要用它；只动测试配置，不改被测代码；代价：全局桩可能掩盖将来依赖真实尺寸的测试，那类测试需自己 mock。
- 2026-10-02 — T2：笔记标签下没有笔记时隐藏渲染/编辑切换 — 无文件可编辑，留着只会是个无效按钮；状态图标仍显示。
- 2026-10-02 — T1：组件测试没有现成的查询 mock 先例，新增 `snapshotTestSupport.ts`（测试辅助，`vi.mock('@/composables/queries')` 用）— 保持被测组件不为测试而改。

## 意外与发现

<!-- 执行中的意外：日期 — 现象 — 原因/处理 -->

## 阻塞

无。

## 验证记录

<!-- 每条验收标准对应的命令、输出摘要、截图路径 -->

| AC | 证据 |
|---|---|
| AC1 | `WorkbenchSplit.spec.ts`（三面板 + 两个分隔条）；L4：页面无「画布」标题行，拖动分隔条后对话/画布宽度变化（对话被限制在最小 280px），`reka:workbench-split` 写入 localStorage，刷新后宽度恢复 |
| AC2 | `WorkbenchSplit.spec.ts`（默认折叠）、`SnapshotRail.spec.ts`（折叠窄条显示图标与数量）；L4：首次进入折叠，点击展开，刷新后展开状态与宽度保持 |
| AC3 | `WorkbenchSplit.spec.ts`（窄屏无分隔条、快照栏展开）；L4 窄屏 800px：导航、对话、画布上下堆叠（发现并修复网格行被压扁的重叠，见决策记录） |
| AC4 | `snapshotSelection.spec.ts`（`resolveDiffTarget`）、`SnapshotTimeline.spec.ts`、`SnapshotDetail.spec.ts`（单选/双选/初始快照/二次确认回滚/忙时禁用）；L4：选中快照后下半部分显示详情与「回滚到此」 |
| AC5 | `BriefStatusIcon.spec.ts`（四级、`aria-label`、聚焦弹气泡、`unknown` 无列表）；L4：悬停红叉图标弹出气泡，含结论与 6 条错误 |
| AC6 | `EditModeToggle.spec.ts`、`TopicCanvas.spec.ts`（同一行、共用切换、换标签/笔记回渲染、运行中退出编辑并置灰）；L4：状态图标与渲染/编辑图标右对齐在标签行 |
| AC7 | `make check` 全绿（见下）；ARCHITECTURE、QUALITY 已更新；独立评审见进度 |

证据说明：L4 截图是在内置浏览器里逐项查看的（隔离端口 8001/5174），没有另存文件。
