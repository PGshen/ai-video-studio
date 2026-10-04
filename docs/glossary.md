# 术语表

代码、文档和对话中统一使用下面的术语。英文一列是代码中的命名。

| 术语 | 英文 | 含义 |
|---|---|---|
| 想法卡片 | idea | 选题池中的一条候选选题：标题、卖点、反直觉点、标签、四项评分（反直觉/可论证/可视化/新鲜度，1–5）；状态 `idea`/`archived`；一张卡片可以创建多个项目（项目的 `idea_id` 指向它，见 [ADR 0017](decisions/0017-一张选题可以创建多个项目.md)） |
| 头脑风暴 | brainstorm | 没有项目的对话，agent 联网搜索并往选题池写想法卡片；阶段名 `brainstorm` |
| 选题简报 | brief | 选题打磨阶段的产物 `topic/brief.md`：七个固定章节，关键事实逐条带出处和把握程度（高/中/低），由 `check_brief` 检查结构 |
| 无项目会话 | workspaceless session | `project_id` 为空的会话（头脑风暴）：没有工作区和快照，cwd 是每轮重建、一轮结束即删的 scratch 目录 |
| 联网模式 | web mode | `STUDIO_WEB_MODE`：`tools`（默认，自建 `web_search`/`fetch_url`）或 `native`（运行时原生联网），互斥，见 ADR 0010 |
| URL 来源规则 | URL provenance | `fetch_url` 只能抓本会话搜索结果里出现过的、或用户消息里给出的 URL，模型不能凭空构造 URL |
| 选题池 | idea pool | 所有想法卡片的集合，头脑风暴的产出放在这里 |
| 项目 | project | 从一张想法卡片创建，完整走完三个阶段，产出一个视频 |
| 阶段 | stage | `topic`（选题打磨）、`narrative`（叙事）、`animation`（动画，含成片）；另有不属于项目的 `brainstorm` |
| 阶段状态 | stage status | `locked`（未开放）、`active`（进行中）、`finalized`（已定稿）、`stale`（上游已变更） |
| 工作区 | workspace | 一个项目的文件目录 `data/projects/<id>/`，产物的权威来源 |
| 产物 | artifact | 阶段的主要输出文件：`brief.md`、`narrative.json`、`scenes/*.py`、`final.mp4` |
| 画布 | canvas | 工作台右侧显示和编辑产物的区域 |
| 会话 | session | 某个阶段中的一段对话，绑定一个模型配置；一个阶段可以有多个会话，同一时刻只有一个处于活动状态 |
| 轮次 | turn | 用户发一条消息，到 agent 完成回复，这是一轮 |
| 轮次事件 | turn event | 一轮中持久化的事件：文本块、工具调用、工具结果、快照、回退建议等 |
| 活动组 | activity group | 对话页里同一 turn 连续的思考与工具调用，渲染成一个可折叠的整体，组内每一行还能单独折叠（`groupTimeline`、`ActivityGroup`） |
| 思考事件 | thinking event | 模型的推理文本：`thinking_delta`（瞬时、流式）与 `thinking`（落库、可回放），尽力透传、模型不给就没有，见 ADR 0013 |
| 上下文前言 | turn preamble | 每轮附在用户消息之前的现状说明：用户编辑、上游变更、被还原的越界改动等 |
| 运行时 | runtime | agent SDK 的适配器：`claude`、`openai`，以及测试用的 `fake` |
| 模型配置 | model profile | 模型、接入方式、价格、预算上限，决定使用哪种运行时 |
| 业务工具 | business tool / ToolSpec | 我们自己定义的工具，只定义一次，由适配层转成两种 SDK 的格式 |
| 原生工具 | native tool | SDK 自带的工具，例如 Claude 的 Read/Edit/Bash、OpenAI 的 ApplyPatchTool |
| 兜底工具集 | fallback tools | 模型用不了原生工具时，由我们提供的最小文件工具（联网工具是单独的 `web_search`/`fetch_url`，见联网模式） |
| 快照 | snapshot | 某一时刻工作区的清单 `{路径: 内容哈希}`，内容存在 `data/blobs/` 中 |
| 定稿 | finalize | 负责人确认某个阶段的产物，记录定稿快照，并开放下游阶段 |
| 上游只读副本 | upstream copy | `upstream/<stage>/`，上游定稿版本的只读副本，每轮开始前刷新 |
| 越界检查 | scope guard | 每轮结束时，还原本阶段可写范围之外的改动 |
| 工具托管文件 | tool-managed file | 只能由工具写入的文件，例如 `narrative/timing.json` |
| 回退建议 | upstream suggestion | 下游 agent 对上游产物提出的修改建议；只能向直接上游提；状态 `open`/`applied`/`dismissed`，在对话流里显示为卡片，阶段导航上有待处理数量的角标 |
| 风格 | style | 风格库里的一套风格：磁盘上的一个目录 `data/styles/<id>/`，创建项目时复制进项目的 `style/` 目录（之后与风格库脱钩）；名称、简介、分类写在 `STYLE.md` 的 frontmatter（ADR 0019，原「风格预设」存 SQLite 的 `style_presets` 表，已取代） |
| 风格草稿 | style draft | 编辑一套风格时的服务端工作副本 `data/style-drafts/<id>/`：用户在编辑器里改的、AI 对话改的都是它，点「保存」校验通过才覆盖正式版本，「放弃修改」删除它；从未保存过的新风格只有草稿（`is_new`） |
| 风格对话 | style chat | 编辑态右侧的 AI 对话：`style` 阶段的会话，没有项目，属于一套风格（`sessions.subject_id`），agent 的工作目录就是这套风格的草稿目录 |
| skill 形态目录 | skill-shaped style directory | 一套风格的目录结构：入口 `STYLE.md`（frontmatter + 文件索引，每轮先读）+ `references/`（叙事蓝图、配色、动画风格）+ `exemplars/`（金样本）；各阶段提示词说明动笔前读哪些（ADR 0011） |
| 金样本 | exemplar | 一套风格附带的范例（镜头结构与旁白语感），放在 `style/exemplars/` |
| 会话内换模型 | model switch | 会话中途换成同 runtime、同 provider 的另一个模型配置，对话记忆保留；换后第一轮有 `model_switched` 提示（ADR 0012） |
| 有效联网模式 | effective web mode | 界面设置（`settings.web_mode`）优先，没设置时用环境变量 `STUDIO_WEB_MODE`；`TurnRunner` 每轮读一次 |
| 镜头 | scene | 视频的最小内容单元，有稳定的 `id`（slug），对应一个旁白段落和一个代码文件 |
| 节拍 | beat | 镜头内的一个动画时间点，由 `cue_text` 锚定在旁白中 |
| 预览渲染 | preview render | 低清渲染单个镜头并抽取关键帧，供视觉自检使用 |
| 视觉自检 | visual self-check | agent 查看预览关键帧，自己发现并修复画面问题 |
| 成片 | final render | worker 以最终画质一次渲染全部镜头，合成音频（不叠字幕，见 ADR 0016） |
