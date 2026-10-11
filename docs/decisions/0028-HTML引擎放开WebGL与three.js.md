# 0028：HTML 引擎放开 WebGL 与 three.js，出帧默认用 GPU

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳 |
| 日期 | 2026-10-11 |
| 相关 | [webgl-3d 计划](../plans/active/webgl-3d.md)、[WebGL 实测](../references/webgl-spike.md)、[ADR 0021](0021-HTML引擎与配乐阶段.md)、[HTML 视频流水线设计](../design/2026-10-04-html-video-pipeline.md) §1 非目标、[时间轴与 HTML 引擎设计](../design/2026-10-04-timeline-html-engine.md) §5–§6 |

## 背景

HTML 引擎的镜头约定是 `draw(ctx, lt, env)`，`ctx` 是主画布的 Canvas 2D 上下文，出帧时对主画布 `#c` 调 `toDataURL`。ADR 0021 以"确定性和环境风险"为由第一版不做 WebGL，设计文档也把 WebGL 列为非目标。负责人希望支持 3D，并且让模型按画面需要自己选技术（Canvas 2D、WebGL、SVG），不要写死成 Canvas 2D。

2026-10-11 的实测（[webgl-spike](../references/webgl-spike.md)）消除了当初的顾虑：

- headless Chromium 默认就有 WebGL2；拿不到 GPU 时自动用 SwiftShader 软件渲染，不会不可用。
- 软件渲染和 GPU 下，同一台机器上逐帧结果都确定（倒序重渲、新页面、重启浏览器，哈希都一致）。
- 速度：软件渲染下重 3D 约 250 毫秒/帧，GPU 下约 22 毫秒/帧；GPU 也让 2D 出帧从 28 毫秒降到 12 毫秒。
- 代价：开 GPU 会改变 2D 画面的字节（肉眼一致），GPU 帧只保证同一台机器可复现，预览（用户浏览器）和成片会有边缘抗锯齿的差别。

## 决定

1. **镜头约定不变，只放开内部技术**：镜头仍导出 `draw(ctx, lt, env)`，最终画面必须落在主 2D 画布上。镜头内部可以用 Canvas 2D、`Path2D`/SVG 图片资产，或 WebGL（画到离屏画布后 `ctx.drawImage` 贴回）。帧仍然必须是 `(lt, env)` 的纯函数。
2. **内置 three.js 核心**，固定一个版本（计划里定为 `three@0.186.1` 或执行时的最新稳定版），把 `build/three.cjs` 和许可证放进 `engines/render/html/vendor/`，用和镜头一样的 CommonJS 包装挂成全局 `THREE`。**只在 agent 的脚本里出现 `THREE` 标识符时才装配进页面**，纯 2D 项目的页面和缓存键不变。第一版不带 addons（没有 `GLTFLoader`，资产白名单不加 `.glb`），3D 几何体全部由代码生成。
3. **共享 WebGL 上下文**：运行时提供 `env.gl()`（一张懒创建、全页共享的 1920×1080 离屏 WebGL2 画布）和 `env.three()`（基于它的共享 `THREE.WebGLRenderer`）。镜头不自己 `new WebGLRenderer`，避免多镜头时超过 Chromium 的上下文数量上限（超出后最早的上下文会丢失）。
4. **确定性在运行时兜底**：页面在所有脚本之前把 `Math.random` 换成带固定种子、每次 `renderAt` 开头重置的伪随机数，把 `Date.now`、`performance.now` 冻结为 0，`requestAnimationFrame`/`setTimeout`/`setInterval` 设为不执行回调。内置库（three.js）不过静态检查；agent 自己写的脚本静态检查规则不变。
5. **出帧默认用 GPU**：浏览器用新版 headless（Playwright `channel="chromium"`）并允许 GPU；新增开关 `STUDIO_RENDER_GPU`（默认 `true`），设为 `false` 时回到现在的 headless shell 软件渲染，供排查问题用。没有 GPU 的机器照样能出片，只是慢。
6. **缓存键记录渲染器**：浏览器启动后读一次 WebGL 的 `UNMASKED_RENDERER` 和浏览器版本，作为渲染器签名并进成片的画面缓存键；`ENGINE_VERSION` 升到 `html-v2`。换机器、换 GPU 驱动、切换开关都会让画面缓存失效重渲，不会误命中。
7. **出帧耗时进检查**：`validate_scenes_html` 报告每个镜头的平均出帧耗时与当前渲染器；超过阈值（定为 120 毫秒/帧，相当于一分钟成片约 3.6 分钟出帧）给警告，不算错误。
8. **提示词给"技术选择"指引和一份 three.js 金样本**：讲解（`animation_html`）和短片/MV（`produce`）两套提示词都写明三种技术各自适合什么，3D 只在内容需要时用；金样本 `webgl-techniques.js` 示范共享渲染器、用 `lt` 驱动相机和物体、确定性的程序化几何体。

已批准的设计文档不改；HTML 视频流水线设计 §1 非目标里的"WebGL"、时间轴与 HTML 引擎设计里 Canvas 2D 唯一、浏览器启动方式的部分，由本 ADR 取代。ADR 0021"考虑过的方案"里否定 WebGL 的那条，由本 ADR 的实测结论推翻。

## 考虑过的其他方案

- **继续软件渲染，GPU 只作为可选项**：所有机器结果一致、缓存可以跨机器复用，但重 3D 慢 7 倍左右；负责人选择默认用 GPU。
- **让镜头自己 `new THREE.WebGLRenderer`**：最自由，但每个镜头一个上下文，镜头一多就会超过上限、出现上下文丢失；共享渲染器同样能做到所有效果。
- **用 ES module 加载 three.js（`<script type="module">` 加 import map）**：模块脚本是延迟执行的，镜头脚本在模块加载期拿不到 `THREE`；改成全部模块化要重写组装和预览，不值得。`three.cjs` 套上现有的 CommonJS 包装就能用。
- **每个页面都装 three.js**：省掉检测逻辑，但纯 2D 项目的预览页多 1 MB 以上，所有老项目的画面缓存也会白白失效一次。
- **同时内置 `GLTFLoader` 与 `.glb` 资产**：能用现成模型，但加载是异步的，就绪流程和体积限制都要另外设计；负责人决定第一版不做。
- **允许 DOM/CSS 动画**：出帧只截主画布，DOM 截不到；CSS 动画也不能按任意 `t` 精确定位。仍然不做。

## 影响

- 模型可以按画面需要选择 2D、SVG 或 3D；3D 内容（地球、分子、空间图表、粒子场）不再要手写投影。
- 所有项目的画面缓存会在升级后失效一次（`ENGINE_VERSION` 变化加 GPU 改变 2D 字节），第一次重新渲染成片会慢一些。
- 成片只在同一台机器上可复现；同一项目在 Mac 和 Windows 上渲染出的字节不同（肉眼一致）。
- three.js 版本升级要当成依赖升级处理：重新跑金样本和确定性测试，并升级 `ENGINE_VERSION`。
- Windows 上新版 headless 用 D3D11/ANGLE，速度和确定性要在负责人的 Windows 电脑上实测，结论补进 [webgl-spike](../references/webgl-spike.md)。
