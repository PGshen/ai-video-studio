# 子项目 2：统一时间轴与 HTML 引擎

状态：已批准（2026-10-04）。本文是 [多形态视频流水线设计](2026-10-04-html-video-pipeline.md)（以下简称"总设计"）§11 中子项目 2 的实现级设计，不修改总设计；对总设计的补充和修订集中列在 §12。

## 1. 目标与范围

**交付**：用户创建"知识讲解（HTML）"项目后，能走完 `topic → narrative → animation_html`：agent 写 Canvas 2D 场景并用工具看图自检，前端能实时预览，worker 能输出带旁白的 MP4。Manim 路径和老项目不受影响。

**输入**：现有叙事阶段产物 `narrative/narrative.json` 与 `narrative/timing.json`（每镜头的配音时长与 beat 起止，相对镜头起点）。

**非目标**（沿用总设计 §1，并补充）：配乐、节拍网格、短片与 MV 形态（子项目 3/4）；歌词；上游时间轴变化摘要；项目级分辨率与 fps 设置。

**一份设计，两份计划**：

| 计划 | 内容 | 验收 |
|---|---|---|
| 2A | `studio.timeline`；`engines.render.html`（组装、运行时、静态检查、浏览器池、probe、字体）；`animation_html` 阶段（提示词、`prepare_turn`、两个工具）；注册与 import-linter 契约；阶段层测试；真实模型冒烟 | agent 能在界面里写出 HTML 镜头并用工具自检；"知识讲解（HTML）"可创建 |
| 2B | 预览端点与前端画布（含实时预览）；`engines.render.html.video` 与 `engines.render.mix`；worker 分流；定稿与 `scene_checks` 泛化；`useScenePlayback` 搬迁 | 成片可渲染、可定稿，实时预览可用 |

## 2. 已确认的决定

| 项 | 决定 | 依据 |
|---|---|---|
| 设计与计划的切分 | 一份设计、两份计划（2A/2B） | 2026-10-04 负责人确认 |
| 时间轴实现范围 | schema 与"小节.拍"记法一次写全；`build_timeline` 只实现旁白层，其余层传入即报错 | 同上；避免过早固化尚未设计的源文件格式 |
| 中文字体 | 随仓库附带 Noto Sans SC（OFL）woff2，与 Anton、Space Mono 一起由引擎提供 | 同上；字形在任何机器上一致，成片可复现 |
| HTML 引擎接口 | 自有数据类型和函数，不实现 Manim 形状的 `RenderEngine` 协议 | 现有协议以代码字符串和旁白文本为输入，HTML 引擎以工作区目录加时间轴为输入、以帧为单位出图 |
| 组装页面的服务方式 | 纯函数 `assemble` 加路由表；进程内用 `page.route` 供给文件，不开端口；前端 iframe 走 api 只读端点现场组装 | 同上 |
| 时间硬编码检查 | 用"beat 敏感度测试"取代总设计 §12 提到的重定时测试 | 见 §6.3 |
| 成本控制 | 只靠提示词和单镜头预览，不加系统层限制 | 同上 |
| 字幕 | 提示词明确不画字幕 | ADR 0016 |
| 绘图库 | 不提供 | ADR 0021 |

## 3. 小试结论对设计的约束

[html-canvas-agent-spike](../references/html-canvas-agent-spike.md)（2026-10-04）证明：只给 `env` 契约和一个金样本，真实模型能稳定写出可运行、逐帧确定的场景。三次运行首次预览均无报错，38 个采样时刻在三种渲染顺序下像素一致。它同时暴露了四个问题，本设计逐条处理：

| 问题 | 处理 |
|---|---|
| 一次运行没有使用 `env.cue()`，把 beat 时刻写成字面量 | 提示词禁止字面秒数；校验器加静态规则与 beat 敏感度测试（§6.3） |
| 角标和公式的小字不可读 | 提示词规定所有承载信息的文字字号下限；校验器对字面量字号给警告 |
| 3 个镜头需要 11 到 14 分钟 | 提示词规定按镜头顺序逐个"写 → 校验 → 预览 → 修"，全片风格沉淀到 `animation/lib/`，只做一次全量校验 |
| 镜头边界帧差偏大 | `render_preview_html` 报边界帧差 |

## 4. `studio.timeline`（纯能力层）

位置 `backend/src/studio/timeline/`：`schema.py`、`notation.py`、`build.py`。只依赖标准库和 pydantic；加一条 import-linter `forbidden` 契约，禁止 import `studio.*` 中 `config` 以外的模块。

### 4.1 数据结构

完整 schema 按总设计 §4.3：`duration`、`grid`、`sections`、`narration`、`moments`、`music`、`lyrics`。所有时间是**全局秒**。子项目 2 只产出 `duration`、`sections`、`narration`，其余为空值（`grid`、`music` 为 `null`，列表为空）。

- `sections`：对应叙事镜头；起点为前序镜头配音时长累加，镜头之间无间隙（与 Manim 路径一致）。
- `narration`：`[{ scene_id, start, end, beats[{ start, end, cue_text }] }]`，beat 时刻已换算为全局秒。

### 4.2 构建

- `build_timeline(layers: TimelineLayers) -> Timeline`。`TimelineLayers` 含 `narration`，并预留 `grid`、`moments`、`music` 字段；预留字段一旦传入即抛 `LayerNotSupported`。子项目 3/4 在不改 schema 的前提下补这几层。
- `narration_from_documents(narrative_doc, timing_doc)`：纯函数，入参是已解析的 dict。合并 `narrative.json` 的 `cue_text` 与 `timing.json` 的 `start_seconds/end_seconds`；校验每个镜头都有 timing、beat 数一致、beat 落在镜头时长内。问题一次性汇总成中文错误列表（`TimelineError`）。
- `timeline_hash(tl)`：规范化 JSON 的 sha256。
- 读文件由调用方负责（阶段、worker、api），本模块不碰文件系统。

### 4.3 记法换算

`notation.py`：`parse_at("3.2", bpm)`、`parse_at("4.1+1/16", bpm)` 等，一次写全并测试；子项目 2 无调用方。

### 4.4 谁在何时生成

- 阶段 `prepare_turn`：读 `upstream/narrative/{narrative,timing}.json`（已定稿版本），写 `upstream/timeline.json`。该文件只读、不进快照，语义同 `upstream/` 其余内容。
- worker：从工作区顶层 `narrative/` 重新计算（与 Manim 路径读法一致，见 worker 模块说明 D14），哈希写入 `final.json`。
- 预览端点：从 `upstream/narrative/*.json` 在内存中构建，与 agent 看到的一致。

## 5. `engines.render.html`（纯能力层）

位置 `backend/src/studio/engines/render/html/`。依赖 `config`、playwright、Pillow。不实现 `RenderEngine` 协议。

### 5.1 模块

| 文件 | 职责 |
|---|---|
| `assemble.py` | `assemble(workdir, timeline) -> AssembledPage`：HTML 文本加路由表（字体、`animation/assets/*`）；`runtime.js` 和字体作为包资源随包分发 |
| `runtime.js` | 页面运行时：把 `scenes/*.js` 包成模块，暴露 `window.renderAt(t)` 与 `window.ready` |
| `static_check.py` | 剥离注释后匹配禁用 API，报告文件与行号 |
| `browser.py` | `HtmlBrowser`（异步上下文）：启动 Chromium，`page.route` 供给文件，等 `document.fonts` 就绪；`BrowserPool`；模块级 `get_browser_pool()`/`close_browser_pool()` |
| `probe.py` | 冒烟运行、确定性比对、beat 敏感度测试、单镜头采样、拼缩略图 |
| `video.py`（2B） | 逐帧取图，经管道交给 ffmpeg，输出无声 MP4，带进度回调 |

### 5.2 页面与场景契约

镜头文件 `animation/scenes/<section_id>.js` 导出 `{ draw(ctx, lt, env), pad? }`。`lt` 是镜头内局部时间；`pad: { in, out }` 允许提前或延后绘制以做转场，合成器按镜头顺序叠画重叠区间。每个镜头前后重置变换、透明度和混合模式；镜头异常包装为 `[scene <id> @lt=<秒>]` 加 JS 堆栈。

`env` 的字段（所有时间是镜头局部秒）：

| 字段 | 说明 |
|---|---|
| `W`、`H`、`CX`、`CY` | 画布 1920×1080 与中心 |
| `t`、`len`、`duration` | 全局时间、本镜头时长、全片时长 |
| `section`、`sections` | 当前镜头 `{ id, label, index }` 与全部镜头 |
| `beats` | `[{ start, end, text }]`，本镜头旁白 beat |
| `cue(i)`、`cueEnd(i)` | 第 i 个 beat 的起点与终点；越界抛 `RangeError` |
| `assets` | `animation/assets/*` 的已解码图像对象，按文件名取；缺失时抛明确错误 |
| `bt(n)`、`bar(n)` | 本阶段无网格，调用抛错 |
| `hit(name)`、`energy(t)`、`moment(i)` | 预留签名，本阶段恒为空；子项目 3 填值，契约不变 |

运行时在置 `ready` 之前预解码全部 `assets/*`（场景无法 `await` 图片）。这是对总设计 §5.1 的补充，见 §12。

项目内复用放 `animation/lib/*.js`（agent 自建自维护），可选全局后期 `animation/global.js`（导出 `post(ctx, t, env)`）。引擎不提供缓动、形变、粒子等库。

### 5.3 字体

- 引擎随包附带 Anton、Space Mono（400/700）、Noto Sans SC（400/700，按常用字裁剪）；风格目录 `style/fonts/*.woff2` 作为附加来源，沿用总设计 §5.2。
- 裁剪由一次性脚本 `scripts/build_fonts.sh` 完成（`pyftsubset`，开发期工具，不是运行时依赖）；产物、OFL 许可文件和字符覆盖表（纯文本）入库。子集字符范围与文件体积在计划里实测后确定。
- 引擎在 `document.fonts` 就绪后才出帧。

### 5.4 浏览器生命周期

- api 进程：`BrowserPool` 懒启动，信号量限制 2 个页面并发，崩溃自动重启并重试一次，空闲 10 分钟关闭，lifespan 退出时收尾；排队超过 60 秒报"预览繁忙"。
- worker：每个任务单独启动浏览器，结束即关，不常驻。
- 测试通过 `set_browser_pool()` 注入替身。

### 5.5 出帧与编码（2B）

默认 1920×1080、30fps，与现有 worker 常量一致；`canvas.toDataURL('image/jpeg', 0.92)` 经管道交给 `ffmpeg libx264 yuv420p CRF 15`。实测出帧速度，结论写进 references。

## 6. `animation_html` 阶段

位置 `backend/src/studio/stages/animation_html/`，与其他阶段互不 import。

### 6.1 阶段定义

| 项 | 内容 |
|---|---|
| `name` / `allow_web` | `animation_html` / 否 |
| `reads()` | `[narrative, beatsheet, music]`；与流水线求交后，讲解形态实际只有 `narrative` |
| 可写范围 | `animation/scenes/*.js`、`animation/lib/*.js`、`animation/global.js`、`animation/assets/*`（图片只允许 svg/png/jpg/webp，单个文件有大小上限，数值在计划里定） |
| `artifact_dirs()` | `animation/scenes`、`animation/lib`、`animation/assets`、`animation/global.js`；计划里先确认前言与 `stage_flow` 的前缀匹配对单文件成立，不成立则改为目录 |
| `finalize_blockers` | 空；定稿走成片流程，与 `animation` 一致 |
| `status_summary` | `scenes/` 下已写 X 个镜头 / 时间轴共 Y 个镜头 |
| 注册 | `main.py` 注册该阶段。`video_kinds.unavailable_reason` 按"流水线里的阶段是否都已注册"判断，所以"知识讲解（HTML）"自动变为可选；短片和 MV 仍因 `concept`/`beatsheet`/`music` 未注册而不可选，无需改代码 |

### 6.2 `prepare_turn(workdir)`

- 生成 `upstream/timeline.json`（§4.4）。
- 把引擎自带的金样本复制到 `upstream/exemplar/canvas-techniques.js`。样本由探索作品 `docs/temp/reel/reel.html` 整理而来（约 300 行，即小试验证过的那份），作为包资源随阶段分发；风格库自己的 `exemplars/` 优先，提示词里两处都提。
- 时间轴不可用（叙事缺失或不合法）时不抛异常：删除旧的 `timeline.json`，工具和提示词报"时间轴不可用：<原因>"。计划里先确认 TurnRunner 对 `prepare_turn` 异常的处理，再定这条细节。

### 6.3 业务工具

两个工具均为异步，通过 `get_browser_pool()` 取页面，因此阶段仍可以是模块级单例。

**`validate_scenes_html(scene_id?)`**：不传则校验全部镜头，只返回文本。

| 检查 | 级别 |
|---|---|
| 缺镜头文件；文件未导出 `draw` | 错误 |
| 禁用 API 的静态检查（`Math.random`、`Date`、`performance.now`、`requestAnimationFrame`、`setTimeout/setInterval`、`fetch/XMLHttpRequest`、外部 URL、`eval`/`new Function`），带行号 | 错误 |
| 冒烟运行：每镜头约 12 个采样点，收集异常和 console 报错，带镜头 id、`lt` 与堆栈 | 错误 |
| 确定性：同一批帧正序、倒序各渲染一次，比对哈希 | 错误 |
| 有旁白 beat 的镜头，其文件和 `animation/lib/` 中没有任何 `cue`、`cueEnd`、`beats` 引用 | 错误 |
| beat 敏感度：逐个 beat 后移约 0.7 秒（镜头长度同步加长），在该 beat 附近重渲染采样点；整个镜头对任何 beat 都无反应 | 错误 |
| beat 敏感度：个别 beat 无反应 | 警告，点名序号 |
| 空白或纯色帧 | 警告 |
| 字面量字号过小（扫描 `ctx.font` 字面量），提示"除非纯装饰否则不可读" | 警告 |
| 旁白或场景字面量中的字符不在内置字体覆盖表里（会显示成方框） | 警告，点名字符 |
| `assets` 里有不允许的类型或超大文件 | 错误 |
| 镜头文件不在时间轴里 | 警告 |

beat 敏感度测试取代总设计 §12 的"重定时测试"：整条时间轴平移抓不到写在镜头内部的局部字面量，而"每个 beat 的时刻必须影响画面"才是想保证的性质。已知盲区是 beat 只驱动静态内容，所以单个 beat 无反应只给警告。

**`render_preview_html(scene_id)`**：

- 先做该镜头的静态检查和冒烟运行；失败直接返回错误，不出图。
- 采样不超过 16 个时刻：镜头起点附近、每个 beat 的起点与终点附近、镜头终点附近，再用均匀采样补足。
- 返回一张 4 列缩略图拼图（每格标注 `t`、`lt`）加文本指标：每帧亮度与对比度；与相邻镜头的边界帧差（阈值按小试量级定，其余镜头 ≤ 2，最大的一次约 5.4）；`pad` 叠画区间是否有重叠帧。
- 仓库里工具层没有"模型是否支持视觉"的判断，图片总是返回，不写文字替代方案。

**`suggest_upstream_change`**：沿用 `stages.common`。

**`scene_checks` 的衔接**：`api/scene_checks.py` 按工具名和文本形状聚合最近结果，2B 把它泛化到两组工具名。两个工具的输出文本保持"全部通过 / 点名镜头 id"的可解析形状，不新增表。

### 6.4 提示词（`prompt.md`，中文）

沿用 Manim 提示词的骨架，内容包括：

- **输入**：`upstream/timeline.json`、`upstream/narrative/narrative.json`、`style/STYLE.md`（每轮先读；风格文件决定画面长相，提示词决定代码怎么写，冲突以提示词为准）。
- **产物布局与 `env` 契约**：§5.2。
- **时间规则**：所有时刻只能由 `env.cue/cueEnd/len` 推出，不许写字面秒数。
- **确定性规则**：禁用 API；随机数用带种子的函数，模块加载期可用，渲染期不再消耗。
- **画面规则**：沿用"画面不重叠、镜头首尾自然、转场不留中间态"；所有承载信息的文字不小于下限，纯装饰的小标签单独说明；**不画字幕**（ADR 0016）。
- **字体**：Anton、Space Mono、Noto Sans SC，只写 CSS 字体名。
- **工作流**：先读风格与金样本，在 `lib/` 建全片的配色与动作基底；再按镜头顺序逐个"写 → `validate_scenes_html(scene)` → `render_preview_html(scene)` → 看图 → 修"；全部完成后只做一次全量校验；提醒不要反复全量预览。

### 6.5 依赖与契约

- `pyproject.toml` 中 `stages` 的 independence 契约加入 `animation_html`；`stages.pipeline` 的 forbidden 列表同样加入。
- `stages` 依赖 `engines`、`timeline` 与依赖表一致；`timeline` 加入 ARCHITECTURE 依赖表。

## 7. 实时预览（2B）

### 7.1 api

- `GET /api/projects/{id}/animation/html-preview/`：组装好的页面，请求时现场组装，用工作区当前内容，不要求先拍快照。时间轴按 §4.4 从 `upstream/narrative/*.json` 构建；上游缺失返回 409 加原因。
- `GET .../html-preview/{path}`：字体与 `animation/assets/*`；路径走 `workspace` 的安全解析，拒绝越界。
- 响应带 `Cache-Control: no-store` 和 `Access-Control-Allow-Origin: *`：iframe 使用 `sandbox="allow-scripts"` 且不带 `allow-same-origin`，是不透明源，字体必须有 CORS 才能加载。
- `GET .../html-preview/meta`：`{ hash, duration, sections[{ id, label, start, end, beats }], audio[{ section_id, url }] }`。`hash` 覆盖场景文件、`lib`、`global`、`assets` 与时间轴。
- 页面额外追加一段**仅预览模式**脚本：接收父页面 `{ type: 'seek', t }`，用 `requestAnimationFrame` 合并后调用 `renderAt`；向父页面回报 `ready` 与 `error{ message }`。导出用的组装不含这段。

### 7.2 前端

在 `features/canvas/animation/` 内扩展，不新建 feature 目录。`ProjectWorkbenchPage` 按阶段 key 分发：`animation_html` 用新的 `HtmlAnimationCanvas`，`animation` 保持不变。三个标签：

- **镜头**：镜头列表来自 `meta.sections`，附文件是否存在和检查状态；代码编辑器复用 `CodeEditor`（计划里先确认它支持 javascript）。
- **实时预览**：iframe 加传输控制（播放/暂停、带镜头刻度的进度条、循环当前镜头、`error` 横幅）。收到现有 `workspace_changed` 事件后重新拉 `meta`，哈希变化才刷新 iframe。
- **成片**：直接复用 `FinalRenderPanel`（读 job 进度，与引擎无关）。

播放时钟：当前镜头配音的 `currentTime` 加该镜头起点；镜头切换时按 `section.start` 对齐并预加载下一段；未配音时回退为 `requestAnimationFrame` 计时。预览与成片的音画对齐允许有小偏差，以成片为准。

`useScenePlayback` 目前在 `features/canvas/narrative/`；`features/*` 之间不许互相 import，所以先搬到 `composables/`。

## 8. 成片（2B）

`final_render` 任务按项目 `settings.engine` 分流；Manim 路径保持原样。HTML 路径：

1. 读工作区顶层 `narrative/{narrative,timing}.json` → `build_timeline` → `timeline_hash`。
2. 检查每个镜头都有文件；静态检查有错则失败并点名。
3. 拍快照（与 Manim 一致）。
4. 画面缓存键：引擎版本、场景源码、`lib`、`global`、`assets` 的哈希、`timeline_hash`、分辨率与 fps。命中则跳过出帧。只缓存无声视频；混音很快，每次重做。
5. `engines.render.html.video` 逐帧出图并交给 ffmpeg；进度回调里同时更新 `progress` 与心跳（`update_progress` 本身不续心跳）。
6. 混音：新增纯能力模块 `engines.render.mix`，用 `adelay + amix(normalize=0)` 按 `timeline.narration` 起点拼旁白轨，AAC，`-movflags +faststart`，时长以时间轴为准。接口预留背景乐轨，子项目 3 再加侧链压低。
7. 写 `output/final.mp4` 与 `output/final.json`。`final.json` 保留现有字段，新增 `engine`、`timeline_hash`、`audio_sources`。

**定稿**：`api/jobs.py`、`api/animation.py` 现在写死阶段名 `animation`，改为按项目流水线解析实际的动画阶段（`animation` 或 `animation_html`），其余逻辑不变；老项目回落到 `animation`。

**架构文档**：ARCHITECTURE 依赖表加入 `timeline`、`engines.render.html`、`engines.render.mix`、`stages.animation_html`；worker 的依赖加 `timeline`。

## 9. 错误处理

| 情况 | 处理 |
|---|---|
| Chromium 未安装 | 工具、预览端点和 worker 都返回明确错误并附 `uv run playwright install chromium`；`make setup` 负责安装 |
| 页面或浏览器在工具调用中崩溃 | 池自动重启并重试一次，仍失败则报错 |
| 池满 | 排队最多 60 秒，超时报"预览繁忙" |
| 场景运行时异常 | `[scene <id> @lt=…]` 加 JS 堆栈 |
| 时间轴不可用 | 工具和前言报原因；预览端点返回 409 |
| 字符不在内置字体子集里 | 校验警告并点名字符 |
| `assets` 类型或体积不合规 | `validate_scenes_html` 报错 |
| 预览 iframe 报错 | 前端横幅显示信息，不影响编辑 |
| 成片失败 | 错误信息带镜头 id、时刻与堆栈；缓存不受影响 |
| worker 任务中断 | 沿用心跳过期回收 |
| 老项目与 Manim 项目 | 路径不变 |

## 10. 测试策略

- **纯函数**：timeline 的 schema、构建、`narration_from_documents`、记法换算、哈希；静态检查（表驱动，含"注释里出现禁用 API 不报错"）；组装、字体与资源路由表、采样时刻选择、拼图。
- **`slow`**（`-m slow`，与现有约定一致，不进 `make check`）：用极小固定场景测引擎的确定性、报错包装、beat 敏感度（一个用 `cue` 的镜头与一个写字面量的镜头）；30 帧视频的帧数与时长（ffprobe）；混音的音轨与时长。
- **阶段与 API**：fake 运行时跑通 `explainer_html` 完整流水线（复用现有叙事夹具）；预览端点的页面、`meta` 哈希变化、路径穿越、CORS 头；worker 分流与 `final.json` 字段；任务和定稿接口对 `animation_html` 生效。
- **前端**：vitest 覆盖传输时钟映射、镜头刻度计算、iframe 消息协议；组件测试覆盖画布标签。L4 由控制者在浏览器中验证：创建 HTML 讲解项目、三个标签、实时预览播放。
- **真实模型冒烟**：新增一个 `make smoke` 用例（`claude-login`，3 个镜头），断言校验全过、beat 敏感度通过、能出成片；夹具基于本次小试。

## 11. 新增依赖与资产

- **依赖**：`playwright`（Python，含 Chromium 下载）。`librosa` 不在子项目 2 引入，留给子项目 4。
- **资产**：Noto Sans SC、Anton、Space Mono 的 woff2 与 OFL 许可文件；字符覆盖表；金样本 `canvas-techniques.js`；`scripts/build_fonts.sh`。

## 12. 对总设计的补充与修订

| 总设计位置 | 变化 |
|---|---|
| §5.1 `env` | 补充 `env.assets`：运行时预解码 `assets/*`，场景同步取用 |
| §5.4 出帧 | 分辨率与 fps 取现有 worker 常量（1920×1080、30fps），不新增项目设置字段 |
| §5.5 预览 | 删除"`supports_vision=false` 时只返回文本指标"：工具层没有该判断，图片总是返回 |
| §5.2 字体 | 明确系统附带字体的来源：Noto Sans SC、Anton、Space Mono，随包分发 |
| §12 风险 | "重定时测试"改为"beat 敏感度测试"（§6.3）；第一条风险（agent 写 Canvas 场景）已由小试验证 |

## 13. 延后事项与风险

**记入 `docs/plans/TODO.md`**：上游时间轴变化摘要（总设计 §9）；项目级分辨率与 fps 设置；短片形态（`bt/bar/hit/energy`）的同类小试，子项目 3 开工前做；真实模型对 `assets` 用法的验证（小试未覆盖）。

| 风险 | 验证方式 |
|---|---|
| api 进程内常驻浏览器的资源占用与稳定性 | 2A 中实测；必要时改为按需启动 |
| 出帧速度与长视频时长 | 2B 中实测，结论写进 references |
| 预览与成片的音画偏差 | 2B 的 L4 验证中对比 |
| 内置字体子集漏字 | 校验警告 + 覆盖表；体积与字符范围在计划里实测后定 |
| `prepare_turn` 异常对 TurnRunner 的影响 | 2A 计划第一项确认 |
