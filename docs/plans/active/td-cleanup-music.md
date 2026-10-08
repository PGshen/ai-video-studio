# td-cleanup-music：音乐与导入这一块的技术债清理

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | produce 阶段之后（整理） |
| 设计依据 | 登记表 [tech-debt.md](../../quality/tech-debt.md) 的 TD-80、TD-75、TD-76、TD-81、TD-83、TD-63、TD-50 |
| 分支 | `td-cleanup-music` |
| 批准记录 | 2026-10-08：负责人同意按建议范围清理；负责人批准计划，用 subagent-driven 执行 |

## 目标

处理登记表里音乐与导入这一块有真实影响、改动小的七条：重新定稿 `concept` 不再误伤 `produce`，慢歌不再被误报"拍点不稳"，"音乐源文件"只有一套判定规则，定稿后不能再换歌，成片前核对脚本，歌词上传端点补齐请求头与资源清理，登记表检查能查出与"已处理"撞号。

## 范围

**包含：**

- TD-80、TD-75、TD-76、TD-81（①②）、TD-83、TD-63。
- TD-50：登记表说成片不再叠字幕、后端已不 import Pillow。**实际核对结果不成立**：`stages/common/picture.py`、`styles/screenshots.py`、`engines/render/html/probe.py`、`engines/audio/picture.py` 都直接 import `PIL`，依赖必须保留。本计划只把 TD-50 作为过时条目关闭，不改 `pyproject.toml`。

**不包含：**

- TD-45（时间字段加时区，改公共接口，等负责人单独批准）。
- TD-84（歌词边角）、TD-82、TD-77、TD-78 等其余音乐类条目，保持登记。
- TD-42 的逐套风格冒烟（用本机登录，另开一件事）。

## 验收标准

- [ ] AC1：`concept` 定稿后，`produce` 产出 `music.wav`、`events.json`、`range.json` 等文件，再重新定稿 `concept`（内容没改）不会把 `produce` 标成 stale；换歌（`music/source.*`）、改分析或改歌词仍会（验证方式：`stage_flow` 的新测试，含短片与 MV 两种夹具）
- [ ] AC2：折叠前拍速低于 60 BPM 的拍点序列，覆盖率接近 1，不再带"拍点不稳"警告；正常拍速的结果与改动前逐位一致（验证方式：`engines/audio` 的新测试 + 原有测试）
- [ ] AC3：时间轴读取、`find_source`、`concept` 定稿三处使用同一个函数找源文件；手工放进多个源文件时定稿被拦并点名文件，时间轴报错文案不变（验证方式：新测试）
- [ ] AC4：`concept` 已定稿时，上传歌曲和歌词的端点都返回 409；未定稿时行为不变（验证方式：`api` 新测试）
- [ ] AC5：直接发起成片渲染时，`music/compose.py` 与 `render.json` 的 `script_hash` 不一致会给出明确错误（验证方式：`test_worker_html_music.py` 新测试）
- [ ] AC6：歌词上传端点没有或写坏 `Content-Length` 时 422，不再 500；`form` 一定被关闭（验证方式：`api` 新测试）
- [ ] AC7：`check_docs.py` 能查出未处理条目与"已处理"表里整号撞号，也能识别 `|TD-60|` 这类少空格的行；带"（部分）"后缀的行不算撞号（验证方式：`scripts` 的测试）
- [ ] AC8：`tech-debt.md` 更新（TD-80/75/76/81/83/63 移到已处理，TD-50 按过时关闭并写明原因），`make check` 为绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：TD-80 `concept` 的产物范围收窄到文件级（完成）

- **目标**：`concept` 只把用户输入类文件算作自己的产物，`produce` 的输出不再引起 stale。
- **涉及文件**：`backend/src/studio/stages/concept/__init__.py`、`backend/src/studio/agent/stage_flow.py: _artifacts_of`、`backend/tests/agent/` 中 stage_flow 相关测试。
- **接口与要点**：
  - `artifact_dirs()` 的语义放宽：条目可以是目录（以 `/` 前缀匹配）或完整文件路径（精确匹配）；签名不变。`_artifacts_of` 的判定改成 `path == entry` 或 `path` 以 `entry.rstrip("/") + "/"` 开头。
  - `ConceptStage.artifact_dirs()` 返回 `["concept"]` 加 `music/source.<ext>`（遍历 `SOURCE_EXTENSIONS`）、`music/analysis.json`、`music/analysis.png`、`music/lyrics.lrc`。
  - 开工时先 grep 所有 `artifact_dirs` 的使用方（前言的 diff、`finalize`、`_reconcile`），确认只靠 `_artifacts_of` 解释条目；有别处按前缀解释的，同步改。
- **测试（先写）**：① 文件级条目只匹配该文件，不匹配同目录兄弟；② 定稿 `concept` 后往 `music/` 写 `music.wav`、`events.json`、`range.json`，再定稿 `concept`，`produce` 保持原状态（短片：定稿时 `music/` 为空；MV：已有源文件）；③ 换 `music/source.mp3` 内容、改 `lyrics.lrc` 仍使 `produce` stale；④ 目录条目（其他阶段）行为不变。
- **完成标准**：以上测试通过，既有 stage_flow 测试不改动即通过。
- **验证命令**：`make check`

### T2：TD-75 慢歌的覆盖率按折叠前的拍点周期算（完成）

- **目标**：覆盖率的分子分母同一口径。
- **涉及文件**：`backend/src/studio/engines/audio/song.py`（`GridFit`、`fit_grid`、`analyze_samples`）、`backend/tests/engines/audio/` 对应测试。
- **接口与要点**：`GridFit` 增加 `raw_period: float`（折叠前的拟合周期，即 `slope`，秒）；`analyze_samples` 里 `expected = max(1.0, duration / fit.raw_period)`。网格、BPM、`offset` 的计算不动，所以 `analysis.json` 里除 `confidence` 与 `warnings` 外的字段在正常拍速下不变。
- **测试（先写）**：① 合成一串周期 1.2 s（50 BPM）的规则拍点，经 `fit_grid` 得到折叠后 100 BPM，`beats_used / (duration / raw_period)` 接近 1；用 `analyze_samples` 的覆盖率部分或抽出的小函数断言置信度不低于警告线（若直接测 `analyze_samples` 需要真实音频，则把覆盖率计算抽成纯函数 `_coverage(fit, duration)` 再测）；② 120 BPM 的既有用例结果逐位不变；③ 真的稀疏（只检测到一半拍点）的序列覆盖率仍低、仍告警。
- **完成标准**：慢歌不再误报，真稀疏仍告警。
- **验证命令**：`make check`

### T3：TD-76 + TD-81 源文件规则统一、定稿后不能换歌、成片前核对脚本（完成）

- **目标**：一套"找源文件"规则；后端拒绝在 `concept` 定稿后换歌词和歌曲；成片前核对 `compose.py`。
- **涉及文件**：`backend/src/studio/stages/common/music_source.py`、`timeline/load.py: _source_file`、`stages/concept/check_concept.py`（或 `ConceptStage.finalize_blockers`）、`api/music_import.py`、`worker_html.py: _music_source`，及各自测试。
- **接口与要点**：
  - `music_source.py` 新增 `find_sources(music_dir: Path) -> list[Path]`（白名单扩展名、仅普通文件、按扩展名顺序）；`find_source` 改为取 `find_sources` 的第一个。`timeline/load.py::_source_file` 用它：0 个报"不存在"，多个报"有多个音乐源文件"（文案保持不变），并保留现有的"解析后在工作区内"检查。注意 `timeline` 不能反向依赖 `stages`（先看 `docs/ARCHITECTURE.md` 的分层规则与结构测试）；若违反分层，把 `SOURCE_EXTENSIONS`/`find_sources` 放到两边都能依赖的层（例如 `workspace` 或 `timeline` 内部），`stages.common.music_source` 重新导出，并在决策记录里写明。
  - `concept` 定稿：`finalize_blockers` 在发现多个源文件时加一条，点名文件。
  - 上传歌曲、上传歌词、删除歌词三个端点：`get_stage(engine, project_id, "concept")` 的 `status == "finalized"` 时 409，文案"创意与要求已定稿，请先重新打开再改歌曲/歌词"。放在现有 `is_project_busy` 检查旁边；共用一个小函数，不要三处各写。
  - `worker_html._music_source`：当 `music/compose.py` 的哈希不等于 `render.json` 的 `script_hash` 时追加错误"music/compose.py 在上次渲染之后改过，需要重新渲染"；文件缺失同样报。解析 `render.json` 时 `script_hash` 缺字段按损坏处理（已有的 `except` 分支）。
- **测试（先写）**：① `find_sources` 多个/零个/软链接指向外部；② 时间轴读取与 `find_source` 在同一目录上结论一致；③ `concept` 定稿被多个源文件拦下；④ 三个端点在 `finalized` 时 409、`active` 时照常，上传被拒时不改磁盘；⑤ 脚本改过/删除后手动渲染报错，没改时通过；既有 `test_worker_html_music.py` 的夹具需要补上正确的 `script_hash`。
- **完成标准**：以上测试通过；前端不用改（它在非进行中时已隐藏上传区）。
- **验证命令**：`make check`

### T4：TD-83 歌词上传端点的请求头与资源清理（完成）

- **目标**：与 `api/styles.py::upload_screenshot_endpoint`（TD-86 已修）同一套处理。
- **涉及文件**：`backend/src/studio/api/music_import.py: upload_music_lyrics_endpoint`、`backend/tests/api/` 对应测试。
- **接口与要点**：`content-length` 非数字或缺失 → 422"请求缺少有效的 Content-Length"；超过 `MAX_LRC_BYTES * 2` 仍用现有文案；`request.form()` 之后用 `try/finally: await form.close()`。不改解析逻辑。
- **测试（先写）**：无 `Content-Length` 的分块请求 422；`Content-Length: abc` 422（现在是 500）；超限 422 文案不变；正常上传不变。
- **完成标准**：以上测试通过。
- **验证命令**：`make check`

### T5：TD-63 登记表检查查出与"已处理"撞号（完成）

- **目标**：`check_tech_debt_ids` 把"已处理"表里的整号也并入比较。
- **涉及文件**：`scripts/check_docs.py`、`scripts/` 下对应测试（没有则新建一个与现有脚本测试同风格的）。
- **接口与要点**：`TD_ROW` 放宽为 `^\|\s*(TD-\d+)\s*\|`；未处理区的号去重，再与"已处理"区**整号**（第一列恰好 `TD-n`，不含"（部分）"等后缀）比较，撞号报错并点名两侧。已有数据中 TD-25/27/39 同时有未处理行和"（部分）"行，必须不报错。
- **测试（先写）**：未处理与已处理撞号报错；`|TD-60|` 无空格被识别；"TD-25（预算部分）"与未处理 TD-25 共存不报错；当前真实的 `tech-debt.md` 通过。
- **完成标准**：`make check` 里的文档检查通过。
- **验证命令**：`make check`

### T6：收尾——登记表与待办（待开始）

- **目标**：文档与实际一致。
- **涉及文件**：`docs/quality/tech-debt.md`、`docs/plans/TODO.md`（无需条目则不改）、本计划。
- **要点**：TD-80/75/76/81/83/63 从未处理表删除，在"已处理"表追加一行（日期、做法、测试名）；TD-81 两点都做了；TD-50 在"已处理"里写"关闭，未做代码改动：Pillow 仍有四处直接使用"，并列出文件；TD-76 的说明里把"仅手工放文件才会出现"改成已拦截。`docs/ARCHITECTURE.md` 若因 T3 的分层调整而变化，同步更新。
- **验证命令**：`make check`

## 进度

- 2026-10-08 — T1 完成：`artifact_dirs()` 条目支持文件级精确匹配（共用 `stage.in_artifacts`，stage_flow 与前言两处使用），`concept` 只声明用户输入文件；新测试 `tests/agent/test_stage_flow_file_scope.py`。
- 2026-10-08 — T2 完成：`GridFit.raw_period` 记录折叠前周期，覆盖率抽成纯函数 `_coverage(fit, duration)`，分子分母同口径；慢歌（<60 BPM）不再误报“拍点不稳”，真稀疏仍告警。
- 2026-10-08 — T3 完成：`find_sources` 成为找歌曲源文件的唯一规则（时间轴读取、`find_source`、`concept` 定稿拦截多个源文件共用）；`concept` 定稿后上传歌曲、上传/删除歌词三个端点回 409；成片前核对 `music/compose.py` 与 `render.json` 的 `script_hash`。
- 2026-10-08 — T4 完成：歌词上传端点要求数字型 `Content-Length`（缺失或非数字回 422，不再 500），超限文案不变，`request.form()` 之后 `try/finally` 关闭表单；测试见 `tests/api/test_music_lyrics.py`。
- 2026-10-08 — T5 完成：`check_tech_debt_ids` 的 `TD_ROW` 放宽空白，未处理区的号再与“已处理”区整号比较，撞号报错点名两表；“（部分）”行不计；测试见 `backend/tests/test_check_docs_tech_debt.py`（脚本无既有测试，放在后端 pytest 内以纳入 `make check`）。

## 下一步

- 从 T6，按计划任务顺序继续。

## 决策记录

- 2026-10-08 — TD-50 不执行：登记表的前提（后端不再 import Pillow）核对后不成立，按"过时"关闭而不是移除依赖。
- 2026-10-08 — TD-81 ② 的脚本核对同时作用于 `music` 阶段（讲解类）和 `produce` 阶段：两者定稿时本来就核对 `script_hash`，成片前补上是同一口径。

- 2026-10-08 — T2：覆盖率按 `raw_period` 计算同样作用于"拍速过快被减半"的情形：此前较长的减半周期把覆盖率封顶在 1，会掩盖拍点缺失；现在稀疏的快歌置信度也会如实下降（干净输入不变）。
- 2026-10-08 — T3 分层：`timeline` 不能 import `stages`，所以 `SOURCE_EXTENSIONS`/`find_sources`/`find_source` 移到 `studio.timeline.music_source`，`studio.stages.common.music_source` 重新导出（既有 import 路径不变）。`find_sources` 只认普通文件，符号链接一律不算（此前时间轴接受指向工作区内的符号链接，现在不接受；上传端点只写普通文件）；时间轴另外保留“解析后在工作区内”的检查，防 `music/` 目录本身是符号链接。多源文件拦截放在 `check_workspace`，`check_concept` 工具与定稿条件同一口径。

## 意外与发现

- TD-50 过时，见上。

## 阻塞

- 无

## 验证记录

- 无
