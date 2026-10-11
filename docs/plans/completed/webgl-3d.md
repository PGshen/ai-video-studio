# webgl-3d：HTML 引擎支持 WebGL 与 three.js，出帧默认用 GPU

<!-- 本计划实现 ADR 0028。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成 |
| 里程碑 | 渲染能力扩展（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [ADR 0028](../../decisions/0028-HTML引擎放开WebGL与three.js.md)（提议）、[WebGL 实测](../../references/webgl-spike.md) |
| 分支 | `webgl-3d`（开工时从 main 切出） |
| 批准记录 | 2026-10-11：负责人批准计划与 ADR 0028；会话内直接执行 |

## 目标

模型写镜头时可以按画面需要选 Canvas 2D、SVG 或 WebGL/three.js；3D 镜头在实时预览和成片里都能正常工作，帧仍然确定。成片出帧默认走 GPU，没有 GPU 的机器自动回落到软件渲染，照样能出片。

## 范围

**包含：**

- 固定版本的 three.js 核心（`build/three.cjs`）放进 `engines/render/html/vendor/`，按需装配进页面。
- 运行时的确定性兜底（`Math.random`、`Date.now`、`performance.now`、定时器），以及共享的 WebGL 上下文 `env.gl()` 和 `env.three()`。
- 浏览器默认用新版 headless 并允许 GPU；开关 `STUDIO_RENDER_GPU`；渲染器签名进画面缓存键，`ENGINE_VERSION` 升到 `html-v2`。
- `validate_scenes_html` 报告出帧耗时与渲染器，超过阈值时警告。
- 两套提示词（`animation_html`、`produce`）加技术选择指引；新增金样本 `webgl-techniques.js`。
- 文档：ARCHITECTURE、references、dev-setup、ADR 状态。

**不包含：**

- three.js 的 addons（`GLTFLoader`、`OrbitControls` 等）和 `.glb`/`.gltf` 资产。
- three.js 以外的第三方库。
- DOM/CSS 动画；WebGPU。
- 前端改动（预览 iframe 里的页面由后端组装，不需要改 Vue 代码；若 T6 发现预览在沙盒 iframe 里拿不到 WebGL，按升级条件停下来）。
- Windows 上的实测（不在本机；作为 TODO 留给负责人的 Windows 电脑，见「下一步」末尾）。

## 全局约束

- 镜头约定 `draw(ctx, lt, env)` 不变；最终画面必须落在主画布 `#c`，出帧方式（`toDataURL`）不变。
- **新依赖只有 three.js 一项**（MIT），以文件形式放进仓库，不进 `pyproject.toml` 或 `package.json` 的运行时依赖；版本写在 `vendor/THREE_VERSION`，许可证放在 `vendor/three.LICENSE`。
- 静态检查规则对 agent 写的脚本不放松；内置库不过静态检查。
- 纯 2D 项目（脚本里没有 `THREE` 标识符）组装出的页面除运行时外不变；`env.gl()`/`env.three()` 都是懒创建，不调用就不建 WebGL 上下文。
- 预览脚本（`_PREVIEW_SCRIPT`）依赖 `requestAnimationFrame`：确定性兜底必须先保存原始函数，系统脚本用保存的那一份，agent 的代码拿到的是不执行回调的版本。
- 慢测试（真实 Chromium）用已有的 `slow` 标记；每个任务结束时 `make check` 为绿，涉及浏览器的任务额外跑 `cd backend && uv run pytest -m slow tests/engines`。

## 验收标准

- [x] AC1：一个只用 three.js 的镜头（金样本）通过 `validate_scenes_html`：静态检查、冒烟、确定性、出帧耗时全部无错误。（验证方式：慢测试 `test_webgl_exemplar_validates`）
- [x] AC2：同一页面里多个镜头共用 `env.three()`，连续渲染 20 个以上镜头切换不出现 WebGL 上下文丢失。（验证方式：慢测试）
- [x] AC3：内置库内部调用 `Math.random`/`performance.now` 不影响确定性：倒序重渲与重启浏览器后帧哈希一致。（验证方式：慢测试）
- [x] AC4：`STUDIO_RENDER_GPU=true`（默认）时本机渲染器是 GPU（Metal）；`false` 时是 SwiftShader；两种情况下缓存键不同。（验证方式：慢测试读渲染器签名 + 单元测试比较缓存键）
- [x] AC5：纯 2D 项目的组装结果不含 three.js；含 `THREE` 的项目包含且只包含一次。（验证方式：单元测试）
- [x] AC6：实时预览里 3D 镜头可以拖动时间轴、正常显示。（验证方式：`preview_start` 打开一个含 3D 镜头的项目，截图）
- [x] AC7：真实模型（本机 Claude 订阅登录）在短片项目里按要求写出至少一个 3D 镜头，成片渲染成功，记录步数与出帧耗时。（验证方式：真实冒烟，结论写进 `references/webgl-spike.md`）
- [x] AC8：`make check` 全绿；`pytest -m slow tests/engines` 全绿。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：放入 three.js 核心（完成）

- **目标**：仓库里有固定版本的 `three.cjs`，并确认它在现有的 CommonJS 包装里能加载。
- **涉及文件**：`backend/src/studio/engines/render/html/vendor/{three.cjs,three.LICENSE,THREE_VERSION}`、`scripts/vendor_three.sh`（一次性取文件的脚本，仿照 `build_fonts.sh`：`npm pack three@<版本>` 到临时目录、解包、复制、写版本号）、`backend/tests/engines/test_html_vendor.py`。
- **接口与要点**：
  - 版本默认 `0.186.1`；执行时如有更新的稳定版，选发布已满两周的那个，并写进决策记录。
  - 先确认 `three.cjs` 没有 `require` 其他模块；有的话停下来记进「意外与发现」，改用 esbuild 打成 IIFE（esbuild 已在前端依赖里，不算新依赖）。
  - 打包后的 wheel/源码树要带上 `vendor/` 下的文件（检查 `pyproject.toml` 的包数据配置）。
- **测试**：单元测试——文件存在、版本号格式、许可证存在；慢测试——用 `HtmlBrowser` 打开只含包装后 `three.cjs` 的页面，`THREE.REVISION` 等于版本号的次版本号。
- **完成标准**：上述测试通过。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow tests/engines/test_html_vendor.py`

### T2：确定性兜底与按需装配（完成）

- **目标**：页面在任何脚本之前装好确定性兜底；agent 脚本引用 `THREE` 时装配 three.js。
- **涉及文件**：`engines/render/html/assemble.py`、新增 `engines/render/html/determinism.js`（系统所有）、`runtime.js`（`renderAt` 开头重置随机数）、`tests/engines/test_html_assemble.py`、`tests/engines/test_html_browser.py`。
- **接口与要点**：
  - `determinism.js`：保存原始 `requestAnimationFrame`/`cancelAnimationFrame` 到 `window.__RAF__`，然后把 `Math.random` 换成带固定种子的 PRNG（暴露 `window.__RESEED__()`），`Date.now`、`performance.now` 返回 0，`requestAnimationFrame`/`setTimeout`/`setInterval` 返回句柄但不执行回调。`new Date()` 构造也要得到固定时刻。
  - `_PREVIEW_SCRIPT` 改用 `window.__RAF__`。
  - `assemble` 新增内部函数 `_uses_three(workdir)`：对场景、`lib`、`global.js` 剥注释后匹配 `\bTHREE\b`（复用 `static_check.strip_comments`）；为真时在 `lib` 之前加入包装后的 three.js 脚本（名字 `vendor/three.js`）。inline 模式同样内联。
  - `page_hash` 也要包含 `determinism.js`，以及（按需的）three.js。
  - `runtime.js` 的 `renderAt` 开头调用 `__RESEED__()`，让渲染期的随机数和调用顺序无关。
- **测试**（先写）：组装结果包含/不包含 three.js（AC5，含注释里写 `THREE` 不算）；`determinism.js` 是第一段脚本；慢测试——镜头在 `draw` 里调用 `Math.random`（通过一个 `lib` 间接调用，绕开静态检查，模拟内置库）时倒序重渲哈希一致（AC3）；预览页 seek 消息仍然生效。
- **完成标准**：测试通过，现有 HTML 引擎测试不倒退。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow tests/engines`

### T3：共享 WebGL 上下文 `env.gl()` / `env.three()`（完成）

- **目标**：镜头通过 `env` 拿到全页共享的 WebGL2 画布和 three.js 渲染器。
- **涉及文件**：`runtime.js`、`tests/engines/test_html_browser.py`（或新文件 `test_html_webgl.py`）。
- **接口与要点**：
  - `env.gl()`：返回 `{ canvas, gl }`，懒创建 1920×1080 离屏画布，`webgl2`、`antialias: true`、`preserveDrawingBuffer: true`；拿不到 WebGL2 时抛出带中文说明的错误。
  - `env.three()`：页面没有 `THREE` 时抛错并提示"脚本里引用 THREE 才会装配 three.js"；否则返回懒创建的共享 `THREE.WebGLRenderer`（基于 `env.gl()` 的画布与上下文，尺寸 1920×1080、`setPixelRatio(1)`）。
  - 每次 `renderAt` 开头不清空 WebGL 画布（由镜头自己 `renderer.render` 决定）；镜头负责 `ctx.drawImage(canvas, 0, 0)`。
  - 监听 `webglcontextlost`，记进 `__LOAD_ERRORS__` 一类的错误列表，让 `render_jpeg` 报出来（`SceneRenderError`），由浏览器池按现有逻辑重建。
- **测试**（先写）：慢测试——两个镜头各自建 three 场景、共用渲染器，30 个时刻来回切换，帧哈希确定且无错误（AC2）；没有 `THREE` 时调用 `env.three()` 的错误文案；纯 2D 页面不创建 WebGL 上下文。
- **完成标准**：测试通过。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow tests/engines`

### T4：默认 GPU、开关与渲染器签名进缓存键（完成）

- **目标**：出帧默认用 GPU，可以用开关关掉；画面缓存按渲染器区分。
- **涉及文件**：`config.py`（`render_gpu: bool = True`，`STUDIO_RENDER_GPU`，空值按默认处理）、`engines/render/html/browser.py`（`HtmlBrowser(gpu: bool)`、启动参数、`renderer_signature`）、`engines/render/html/pool.py`（`_launch_default` 读设置；`BrowserLike` 协议加 `renderer_signature`）、`worker_html.py`（`_cache_key` 加签名、`ENGINE_VERSION = "html-v2"`）、`backend/.env.example`、相关测试。
- **接口与要点**：
  - `gpu=True`：`chromium.launch(channel="chromium", args=[...])`。参数按平台：macOS 不加额外参数（实测新版 headless 已走 Metal），Windows 先不加，留给 Windows 实测；`gpu=False`：保持现在的 `chromium.launch()`。
  - `renderer_signature`：启动后在一个空白上下文里读 `navigator.userAgent` 里的浏览器版本和 WebGL 的 `UNMASKED_RENDERER_WEBGL`，拼成一个字符串缓存在实例上；读不到 WebGL 时签名里写 `no-webgl`，不报错。
  - `channel="chromium"` 启动失败时（例如只装了 headless shell）抛 `ChromiumUnavailable`，错误信息提示运行 `playwright install chromium` 或设 `STUDIO_RENDER_GPU=false`。
  - 预览端点和 agent 工具也走同一个池，同样用 GPU。
- **测试**（先写）：`_cache_key` 对不同签名得到不同键；设置解析（默认 true、`false`、空值）；`_launch_default` 按设置传参（用假 launcher 断言）；慢测试——两种设置下签名分别包含 `Metal`/`SwiftShader`（AC4，只在 macOS 上跑，用 `macos_only` 标记写明原因）。
- **完成标准**：测试通过；`make check` 绿。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow tests/engines`

### T5：出帧耗时与渲染器进镜头检查（完成）

- **目标**：模型能看到每个镜头的出帧耗时和当前渲染器，太慢时收到警告。
- **涉及文件**：`engines/render/html/probe.py`（新增 `frame_cost(page, times) -> float`，毫秒/帧）、`stages/common/scenes/validate_scenes_html.py`、`tests/engines/test_html_probe.py`、对应工具测试。
- **接口与要点**：
  - 复用确定性检查已有的采样时刻，不额外多渲染太多帧（每镜头最多 6 帧计时，第一帧作为预热不计）。
  - 阈值常量 `SLOW_FRAME_MS = 120`；超过时警告"镜头 X 平均出帧 N 毫秒（渲染器：…），一分钟成片约需 M 分钟；减少三角形数量、关闭不需要的抗锯齿或改用 2D"。
  - 结果首行附上渲染器（GPU 或软件渲染），让模型知道当前机器的情况。
- **测试**（先写）：假页面返回固定耗时时，超阈值产生警告、未超不产生；渲染器写进输出。
- **完成标准**：测试通过。
- **验证命令**：`make check`

### T6：金样本、提示词与预览实测（完成）

- **目标**：模型知道什么时候、怎么用 3D；金样本本身能通过检查；预览里 3D 正常。
- **涉及文件**：`stages/common/scenes/exemplar/webgl-techniques.js`（新）、`stages/animation_html/prepare.py` 与 `stages/produce/prepare.py`（多复制一份金样本）、`stages/animation_html/prompt.md`、`stages/produce/prompt.md`（「画面」一节加「技术选择」小节，确定性规则补一句"three.js 动画只能由 `lt` 驱动，不要用 `THREE.Clock`"）、对应 prepare 测试、慢测试 `test_webgl_exemplar_validates`。
- **接口与要点**：
  - 技术选择指引：文字、图标、扁平图形、数据图表用 Canvas 2D；矢量插画用 SVG 资产或 `Path2D`；只有真正需要空间感（旋转的物体、相机运动、光照、深度）时才用 three.js；一个项目可以混用。
  - 金样本示范：模块加载期用带种子的 `rng` 生成几何体与材质；`draw` 里按 `lt` 设置相机和物体姿态，`env.three()` 渲染后 `ctx.drawImage`，再叠 2D 标题；不使用 `THREE.Clock`、`requestAnimationFrame`。
  - 金样本按现有约定只供学习技法，不被 import；放进 `upstream/exemplar/` 的方式和现有两份一致。
  - 预览实测：用种子项目或手写一个含 3D 镜头的短片工作区，`preview_start` 打开，拖动时间轴截图（AC6）。沙盒 iframe 里拿不到 WebGL 时停下来升级。
- **测试**（先写）：prepare 复制了新金样本；慢测试——把金样本装成一个镜头跑 `validate_scenes_html`，无错误（AC1）。
- **完成标准**：测试通过，预览截图存档。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow`

### T7：真实模型冒烟与文档收尾（完成）

- **目标**：确认真实模型能用好 3D，并把文档对齐。
- **涉及文件**：`docs/references/webgl-spike.md`（冒烟结论）、`docs/ARCHITECTURE.md`（`engines.render.html` 一行：`vendor/`、`determinism.js`、`env.gl/three`、GPU 开关与签名；`worker` 一行：`html-v2`）、`docs/runbooks/dev-setup.md`（`STUDIO_RENDER_GPU`、`playwright install chromium` 装的是完整 Chromium）、`docs/quality/QUALITY.md`、ADR 0028 状态改为「已采纳」、`docs/plans/TODO.md`。
- **接口与要点**：
  - 冒烟用本机 Claude 订阅登录（不产生 API 费用，见 [verification.md](../../runbooks/verification.md)）：建一个短片项目，`concept` 里写明"至少一个镜头用 3D 呈现旋转的地球/分子"，走完 `produce` 并渲染成片；记录步数、出帧耗时、成片耗时、遇到的问题（AC7）。
  - 冒烟暴露的提示词问题在本任务内修；超出范围的记进 TODO。
  - TODO 新增：Windows 上 GPU/软件渲染实测（负责人的 Windows 电脑），以及 `.glb` 模型导入（若负责人以后需要）。
- **完成标准**：AC1–AC8 都有证据，写进「验证记录」。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow`

## 进度

- 2026-10-11 — T1 — three.js 0.186.1 打成 IIFE 放进 `vendor/three.iife.js`（736 KB），`vendor/__init__.py` 提供 `three_script()`/`three_version()`；测试 4 个通过
- 2026-10-11 — T2 — `determinism.js` 作为第一段系统脚本（种子随机数每次 `renderAt` 重置、时间冻结为 0、定时器不执行），预览改用 `__RAF__`；`THREE` 出现在 agent 脚本（剥注释后）时装配 three.js，`page_hash` 跟随；assemble 新增 7 个用例、浏览器慢测试 2 个，`pytest -m slow tests/engines` 55 个全绿
- 2026-10-11 — T3 — `runtime.js` 加 `env.gl()`/`env.three()`（懒创建、全页共享；每个镜头第一次取用时清空画布并复位渲染器状态）；`browser.py` 过滤 Chromium 的 WebGL 驱动性能提示；新文件 `test_html_webgl.py`（9 个，含 5 个慢测试），`pytest -m slow tests/engines` 60 个全绿
- 2026-10-11 — T4 — `STUDIO_RENDER_GPU`（默认 true）；`browser.launch_options`、`HtmlBrowser(gpu=…)`、`renderer_signature()`；`HtmlBackend.renderer_signature` 进 `_cache_key`，`ENGINE_VERSION = html-v2`；全部慢测试（76 个）在 GPU 默认下通过
- 2026-10-11 — T5 — `probe.frame_cost`（`render_jpeg` 计时，首帧预热不计）；`validate_scenes_html` 超过 `SLOW_FRAME_MS = 120` 时警告，结果末行写出帧渲染器（软件渲染时注明）；`BrowserPool.renderer_signature()`，`BrowserLike` 协议加同名方法
- 2026-10-11 — T6 — 金样本 `webgl-techniques.js`（点阵地球 + 按 beat 生长的航线 + 2D 标题），两个阶段的 `prepare_turn` 都复制；两套提示词加「技术选择」与 `env.three()`/`env.gl()`；金样本在真实浏览器里通过 `validate_scenes_html` 且无警告；隔离实例里实时预览能显示、拖动、播放 3D 镜头（AC6）
- 2026-10-11 — T7 — 冒烟 `test_webgl_reel_claude_login` 通过（共用 `_run_motion_reel`）；ARCHITECTURE、dev-setup、verification、QUALITY、`.env.example` 已更新
- 2026-10-11 — 评审 — `code-review high`（main...webgl-3d）提出 10 条，修了 8 条：渲染器复位补全（`autoClear*`、`sortObjects`、`shadowMap`）；上下文恢复后可以继续用；静态检查禁用 `THREE.Clock`/`setAnimationLoop`；读取渲染器签名失败时转成 `ChromiumUnavailable`；worker 每个任务读一次签名（不再按进程缓存）；`_uses_three` 复用 `static_check.script_files`，并先用子串预筛；新 JS 注释改为英文。没有修的 2 条：出帧计时复用确定性检查的渲染（另开一次计时更清楚，代价每镜头约 5 帧）、worker 读签名要多起一次浏览器（为了正确性有意保留）

## 下一步

- 无。计划已完成，后续事项见 TODO：Windows 上的 GPU 实测、预览首帧黑屏（P3）、`.glb` 模型导入（按需）。

## 决策记录

- 2026-10-11 — 第一版只内置 three.js 核心，不带 addons 和 `.glb` — 负责人选择（范围最小，确定性好控制）。
- 2026-10-11 — 出帧默认用 GPU — 负责人选择；没有 GPU 时自动回落 SwiftShader 已实测（见 references）。
- 2026-10-11 — three.js 用 0.186.1（2026-09-24 发布，已满两周）。
- 2026-10-11 — 用前端已有的 vite（库模式、`iife` 格式、压缩）把 `build/three.module.js` 打成经典脚本，产物定义全局 `var THREE`；不需要 CommonJS 包装，也没有引入 esbuild。产物文件名 `three.iife.js`（计划原写 `three.cjs`）。
- 2026-10-11 — `Date` 换成冻结版构造函数（无参数时是 1970-01-01，带参数照常），不带 `new` 调用返回固定字符串；agent 脚本仍被静态检查禁用 `Date`。
- 2026-10-11 — 共享上下文的"复位"：每个镜头（以及 `global.js`）第一次调用 `env.gl()`/`env.three()` 时把 WebGL 画布清成全透明，three 渲染器的清屏色、tone mapping、输出色彩空间、阴影、裁剪、渲染目标等复位为默认值；镜头需要的设置要在 `draw` 里每次重新设。这样镜头渲染顺序不影响画面（`test_renderer_state_does_not_leak_between_scenes`）。
- 2026-10-11 — 上下文丢失时 `env.gl()` 抛出带说明的错误（`SceneRenderError`），不毒化页面；验证时会换新页面，所以没有额外的池重建逻辑。
- 2026-10-11 — worker 计算缓存键前要知道渲染器：`HtmlBackend` 新增 `renderer_signature`，测试替身返回固定字符串。起初按进程缓存，评审后改为每个任务读一次：Chromium 可能从 GPU 回落到 SwiftShader，缓存的签名会给软件渲染的帧贴上 GPU 的键。`pool._launch_default` 不用改（`HtmlBrowser()` 默认读设置）。
- 2026-10-11 — 渲染器信息放在校验结果的末行（不改首行"校验通过"的格式，已有调用方和测试按首行判断）。
- 2026-10-11 — produce 提示词有 16 000 字节的体积上限（`test_prompt_stays_a_reasonable_size`）：「技术选择」一节压到一段话，加完后 15 993 字节，几乎没有余量；以后再加内容要先删减别处。
- 2026-10-11 — three.js 按需装配（脚本里出现 `THREE` 标识符才装）— 纯 2D 项目的预览页不变大。

## 意外与发现

- 2026-10-11 — three r186 的 `build/three.cjs` 只是转发壳（`process.emitWarning` 加 `require('./three.module.js')`），three 已改为只提供 ES module，所以改走计划里的备选：打包成 IIFE。打包产物里有 21 处 `Math.random`、5 处 `performance.now`、2 处 `requestAnimationFrame`，T2 的确定性兜底确实需要。
- 2026-10-11 — 读回 WebGL 画布（`toDataURL`、`getImageData`）时 Chromium 会输出 `GL Driver Message (OpenGL, Performance, …): GPU stall due to ReadPixels` 的 console 警告，SwiftShader 下也有；原来会被当成页面错误。现在用 `browser.is_driver_performance_note` 过滤。
- 2026-10-11 — 实时预览刚打开时（第一次拖动或播放之前）画面是黑的；用 main 分支的后端对照也一样，所以不是本计划引入的。拖动或播放后正常。已记进 TODO（P3）。

## 阻塞

- 无

## 验证记录

- AC1：`pytest -m slow tests/stages/test_animation_html_tools.py -k webgl` 通过（金样本两个镜头校验通过、没有警告，预览拼图正常）。
- AC2：`test_scenes_share_one_three_renderer_and_frames_are_deterministic`（两个镜头、30 个时刻来回切换，渲染器 1 个、WebGL 上下文 1 个，帧哈希确定）。
- AC3：`test_library_calls_to_nondeterministic_apis_are_seeded`（倒序重渲与新页面哈希一致；`Date.now`、`performance.now` 为 0；定时器回调不执行）。
- AC4：`test_renderer_signature_names_the_actual_renderer`（macOS：开 GPU 是 `Metal`，关掉是 `SwiftShader`）与 `test_a_different_renderer_changes_the_key`、`test_a_different_renderer_does_not_reuse_cached_frames`。
- AC5：`test_three_is_not_assembled_for_a_2d_project`、`test_three_is_assembled_once_before_libs_when_any_script_references_it`。
- AC6：隔离实例（api 8010、前端 5174、临时数据目录，种子 `seed_animation_html_project`，镜头用金样本）。实时预览拖动到 1.1 秒和 2.2 秒都显示 3D 地球，播放时画面推进，控制台没有错误。截图：`data/evidence/webgl-3d/ac6-preview-seek.jpg`、`ac6-preview-playing.png`；出帧参考图 `exemplar-frame-2.9s.jpg`（GPU：`ANGLE Metal Renderer: Apple M4`）。
- AC7：`make smoke SMOKE_ARGS="-k webgl_reel_claude_login"` 通过，用时 17 分钟；5 个镜头都用 three.js，produce 一轮 62 步、$2.24，成片 12.0 秒，出帧加编码 8.0 秒（详见 `references/webgl-spike.md`「真实模型冒烟」）。冒烟跑的是评审修复之前的代码，修复部分由慢测试覆盖。
- AC8：`make check` 全绿（3 249+ 个后端测试、1 273 个前端测试）；`pytest -m slow` 79 个全绿。
