# webgl-3d：HTML 引擎支持 WebGL 与 three.js，出帧默认用 GPU

<!-- 本计划实现 ADR 0028。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 草稿 |
| 里程碑 | 渲染能力扩展（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [ADR 0028](../../decisions/0028-HTML引擎放开WebGL与three.js.md)（提议）、[WebGL 实测](../../references/webgl-spike.md) |
| 分支 | `webgl-3d`（开工时从 main 切出） |
| 批准记录 | 待负责人批准 |

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

- [ ] AC1：一个只用 three.js 的镜头（金样本）通过 `validate_scenes_html`：静态检查、冒烟、确定性、出帧耗时全部无错误。（验证方式：慢测试 `test_webgl_exemplar_validates`）
- [ ] AC2：同一页面里多个镜头共用 `env.three()`，连续渲染 20 个以上镜头切换不出现 WebGL 上下文丢失。（验证方式：慢测试）
- [ ] AC3：内置库内部调用 `Math.random`/`performance.now` 不影响确定性：倒序重渲与重启浏览器后帧哈希一致。（验证方式：慢测试）
- [ ] AC4：`STUDIO_RENDER_GPU=true`（默认）时本机渲染器是 GPU（Metal）；`false` 时是 SwiftShader；两种情况下缓存键不同。（验证方式：慢测试读渲染器签名 + 单元测试比较缓存键）
- [ ] AC5：纯 2D 项目的组装结果不含 three.js；含 `THREE` 的项目包含且只包含一次。（验证方式：单元测试）
- [ ] AC6：实时预览里 3D 镜头可以拖动时间轴、正常显示。（验证方式：`preview_start` 打开一个含 3D 镜头的项目，截图）
- [ ] AC7：真实模型（本机 Claude 订阅登录）在短片项目里按要求写出至少一个 3D 镜头，成片渲染成功，记录步数与出帧耗时。（验证方式：真实冒烟，结论写进 `references/webgl-spike.md`）
- [ ] AC8：`make check` 全绿；`pytest -m slow tests/engines` 全绿。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：放入 three.js 核心（待开始）

- **目标**：仓库里有固定版本的 `three.cjs`，并确认它在现有的 CommonJS 包装里能加载。
- **涉及文件**：`backend/src/studio/engines/render/html/vendor/{three.cjs,three.LICENSE,THREE_VERSION}`、`scripts/vendor_three.sh`（一次性取文件的脚本，仿照 `build_fonts.sh`：`npm pack three@<版本>` 到临时目录、解包、复制、写版本号）、`backend/tests/engines/test_html_vendor.py`。
- **接口与要点**：
  - 版本默认 `0.186.1`；执行时如有更新的稳定版，选发布已满两周的那个，并写进决策记录。
  - 先确认 `three.cjs` 没有 `require` 其他模块；有的话停下来记进「意外与发现」，改用 esbuild 打成 IIFE（esbuild 已在前端依赖里，不算新依赖）。
  - 打包后的 wheel/源码树要带上 `vendor/` 下的文件（检查 `pyproject.toml` 的包数据配置）。
- **测试**：单元测试——文件存在、版本号格式、许可证存在；慢测试——用 `HtmlBrowser` 打开只含包装后 `three.cjs` 的页面，`THREE.REVISION` 等于版本号的次版本号。
- **完成标准**：上述测试通过。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow tests/engines/test_html_vendor.py`

### T2：确定性兜底与按需装配（待开始）

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

### T3：共享 WebGL 上下文 `env.gl()` / `env.three()`（待开始）

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

### T4：默认 GPU、开关与渲染器签名进缓存键（待开始）

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

### T5：出帧耗时与渲染器进镜头检查（待开始）

- **目标**：模型能看到每个镜头的出帧耗时和当前渲染器，太慢时收到警告。
- **涉及文件**：`engines/render/html/probe.py`（新增 `frame_cost(page, times) -> float`，毫秒/帧）、`stages/common/scenes/validate_scenes_html.py`、`tests/engines/test_html_probe.py`、对应工具测试。
- **接口与要点**：
  - 复用确定性检查已有的采样时刻，不额外多渲染太多帧（每镜头最多 6 帧计时，第一帧作为预热不计）。
  - 阈值常量 `SLOW_FRAME_MS = 120`；超过时警告"镜头 X 平均出帧 N 毫秒（渲染器：…），一分钟成片约需 M 分钟；减少三角形数量、关闭不需要的抗锯齿或改用 2D"。
  - 结果首行附上渲染器（GPU 或软件渲染），让模型知道当前机器的情况。
- **测试**（先写）：假页面返回固定耗时时，超阈值产生警告、未超不产生；渲染器写进输出。
- **完成标准**：测试通过。
- **验证命令**：`make check`

### T6：金样本、提示词与预览实测（待开始）

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

### T7：真实模型冒烟与文档收尾（待开始）

- **目标**：确认真实模型能用好 3D，并把文档对齐。
- **涉及文件**：`docs/references/webgl-spike.md`（冒烟结论）、`docs/ARCHITECTURE.md`（`engines.render.html` 一行：`vendor/`、`determinism.js`、`env.gl/three`、GPU 开关与签名；`worker` 一行：`html-v2`）、`docs/runbooks/dev-setup.md`（`STUDIO_RENDER_GPU`、`playwright install chromium` 装的是完整 Chromium）、`docs/quality/QUALITY.md`、ADR 0028 状态改为「已采纳」、`docs/plans/TODO.md`。
- **接口与要点**：
  - 冒烟用本机 Claude 订阅登录（不产生 API 费用，见 [verification.md](../../runbooks/verification.md)）：建一个短片项目，`concept` 里写明"至少一个镜头用 3D 呈现旋转的地球/分子"，走完 `produce` 并渲染成片；记录步数、出帧耗时、成片耗时、遇到的问题（AC7）。
  - 冒烟暴露的提示词问题在本任务内修；超出范围的记进 TODO。
  - TODO 新增：Windows 上 GPU/软件渲染实测（负责人的 Windows 电脑），以及 `.glb` 模型导入（若负责人以后需要）。
- **完成标准**：AC1–AC8 都有证据，写进「验证记录」。
- **验证命令**：`make check`；`cd backend && uv run pytest -m slow`

## 进度

- 无

## 下一步

- 等负责人批准本计划和 ADR 0028。批准后：把本文件移到 `docs/plans/active/`、状态改为「执行中」，从 main 切出 `webgl-3d` 分支，从 T1 开始。
- 开工前确认 `docs/plans/active/windows-native.md` 已验收并移走（同一时间一般只有一份 active 计划）。

## 决策记录

- 2026-10-11 — 第一版只内置 three.js 核心，不带 addons 和 `.glb` — 负责人选择（范围最小，确定性好控制）。
- 2026-10-11 — 出帧默认用 GPU — 负责人选择；没有 GPU 时自动回落 SwiftShader 已实测（见 references）。
- 2026-10-11 — three.js 按需装配（脚本里出现 `THREE` 标识符才装）— 纯 2D 项目的预览页不变大。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 无
