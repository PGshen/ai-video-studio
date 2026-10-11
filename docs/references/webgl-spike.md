# WebGL 可行性实测（HTML 引擎）

日期：2026-10-11。来源：实测（macOS arm64 Apple M4、Playwright 1.63.0 自带的 Chromium，`playwright install chromium`）。目的：为"放开渲染技术、支持 3D"提供数据，[ADR 0021](../decisions/0021-HTML引擎与配乐阶段.md) 曾以"确定性和环境风险"为由不做 WebGL。

## 方法

- 探针页面沿用现有约定：WebGL2 画到**离屏 canvas**，再 `drawImage` 贴回 1920×1080 的主 2D 画布 `#c`，叠一行 2D 文字；出帧与 `browser.py` 相同（`renderAt(t)` 后 `toDataURL`）。
- 场景：手写 WebGL2（没有用 three.js），环面结 + 实例化立方体，Blinn-Phong 光照，带种子的伪随机摆放。两档负载：中（约 6.2 万三角形）、重（约 35.5 万三角形）；`antialias` 开/关。
- 启动配置：
  - `default`：现在 `pool.py` 的 `chromium.launch()`，即 headless shell；
  - `swiftshader`：`--use-angle=swiftshader --enable-unsafe-swiftshader`；
  - `metal`：`--use-angle=metal --enable-gpu --ignore-gpu-blocklist`；
  - `channel="chromium"`：新版 headless，加不加 metal 参数。
- 确定性：4 个时刻取 PNG 哈希，比较同一页面倒序重渲、新页面、重启浏览器三种情况；速度为 60 帧 `toDataURL('image/jpeg', 0.92)` 的平均耗时，不含 ffmpeg 编码。

## 结论

- ✅ **headless Chromium 默认就能用 WebGL2**，不需要额外参数。渲染器是 SwiftShader 软件渲染（`ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device ...))`），`MAX_TEXTURE_SIZE` 8192，MSAA 4 倍。
- ✅ **所有配置下逐帧结果都确定**：同页倒序、新页面、重启浏览器，PNG 哈希全部一致，且不同时刻的帧互不相同。
- ✅ **新版 headless（`channel="chromium"`）和 metal 参数都会走 GPU**（`ANGLE Metal Renderer: Apple M4`），三者的哈希完全相同。
- ✅ **出帧速度**（毫秒/帧，越低越好）：

  | 负载 | default（SwiftShader） | swiftshader 参数 | metal / 新版 headless |
  |---|---|---|---|
  | 中，抗锯齿开 | 52 | 73 | 14 |
  | 中，抗锯齿关 | 38 | 61 | 13 |
  | 重（35.5 万三角形），抗锯齿开 | 247 | 276 | 22–25 |

  对照 [html-video-render.md](html-video-render.md)：重型 2D 场景约 30 帧/秒（约 33 毫秒/帧，含编码）。软件 WebGL 在中等负载下大约是它的 1.5 倍，重负载下慢 7 倍左右，一分钟 30fps 的成片只出帧就要约 7 分钟；GPU 下和 2D 基本持平。
- ✅ **软件渲染和 GPU 的画面差别只在边缘抗锯齿**：t=5.5 时平均绝对差 0.2，约 0.86% 的像素差值大于 8，最大 128；差异像素全部落在几何体边缘，形状、光照、颜色一致。实时预览（用户浏览器走 GPU）和软件导出的成片看起来不会有区别，但**哈希不同**。
- ✅ **开 GPU 也会改变纯 2D 画布的输出**：用同一个重型 2D 场景（阴影模糊、`filter: blur`、中文字）对比，default 和 metal 各自在重启浏览器后都稳定，但两者的哈希不同；metal 更快（12 对 28 毫秒/帧）。所以切换启动参数会让现有的画面缓存和确定性基线**整体失效一次**。
- ✅ **拿不到 GPU 时自动回落到 SwiftShader**（用 `--disable-gpu` 模拟没有 GPU；headless shell 和新版 headless 都一样，带不带 metal 参数也一样）：WebGL2 照样可用，渲染器变成 SwiftShader，速度回到上表"软件渲染"那一列。只有显式加了 `--disable-software-rasterizer` 时 WebGL 才不可用（`getContext('webgl2')` 返回 `null`）。真实的无 GPU 机器（虚拟机、云主机、GPU 在黑名单里的机器）还没有实测。
- ⚠️ 待验证：
  - Windows（`windows-native`）上 SwiftShader 和 D3D11 的可用性与速度；
  - 一台机器上的 GPU 帧，换一台机器（或换驱动、换 Chromium 版本）是否还能复现。按经验不能，所以 GPU 渲染只保证同机确定；
  - three.js 本身（`Clock` 用 `performance.now`、`requestAnimationFrame` 与静态检查的冲突，加载 `.glb` 的异步问题）；
  - 显存、内存占用以及浏览器池在 WebGL 上下文丢失时的恢复。

## 对设计的影响

1. 不改启动参数，现在的约定就能跑 WebGL；问题是软件渲染下重 3D 很慢。
2. 改成 GPU（新版 headless 或 metal 参数）后速度没问题，但要换掉所有缓存基线，确定性也只在同一台机器内成立。现在的缓存键里没有渲染器信息，需要把 `UNMASKED_RENDERER` 并进 `encode_signature`，或者类似的缓存键。
3. 预览和导出不会是同一份像素，只是肉眼一致。`probe` 的确定性检查要在导出用的同一个浏览器配置里跑。
