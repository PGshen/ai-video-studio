## env 契约（所有时间都是本镜头的局部秒）

| 字段 | 含义 |
|---|---|
| `env.W`、`env.H`、`env.CX`、`env.CY` | 画布 1920×1080 与中心 |
| `env.len`、`env.t`、`env.duration` | 本镜头时长、全局时间、全片时长 |
| `env.section` / `env.sections` | 当前镜头 `{ id, label, index }` / 全部镜头 |
| `env.beats` | `[{ start, end, text }]`，本镜头的旁白 beat |
| `env.cue(i)` / `env.cueEnd(i)` | 第 i 个 beat 的起点 / 终点；越界会抛错 |
| `env.assets` | 已解码的资产 |
| `env.three()` / `env.gl()` | 共享的 three.js 渲染器 / 共享的 WebGL2 上下文 `{ gl, canvas }`（见「技术选择」） |

有旁白的项目没有节拍网格：`env.bt`、`env.bar` 会抛错；没有配乐时 `env.hit`、`env.energy` 恒为 0，`env.moment` 为 `undefined`，`env.span` 为空数组。**用旁白 beat 驱动画面的节奏**：画面要在对应 beat 的时刻表达那句话的内容。

## 技术选择

画面最终都落在主画布上，镜头内部用什么技术按内容决定，可以混用：

- **Canvas 2D**（默认）：文字、图标、扁平图形、图表、粒子。
- **SVG**：矢量插画放进 `animation/assets/*.svg`，用 `env.assets` 取出后 `ctx.drawImage`；简单路径用 `new Path2D('M…')`。
- **3D（three.js）**：只在需要空间感时用（旋转物体、相机运动、光照），出帧更慢。脚本引用 `THREE` 才会装入 three.js 核心（无 addons，不能加载模型）。几何体和材质在模块加载期建好，`draw` 只按 `lt`/`env` 设姿态，**不要用 `THREE.Clock`**。用共享渲染器 `env.three()` 渲染后 `ctx.drawImage(renderer.domElement, 0, 0)`，不要自己建渲染器；它的状态每个镜头开始时复位（清屏透明），需要的设置每帧重设；2D 文字在 3D 层之后画。写着色器用 `env.gl()`（共享的 `{ gl, canvas }`）。 3D 金样本：`upstream/exemplar/webgl-techniques.js`。

## 时间规则（最容易出错）

- 所有时刻只能由 `env.cue(i)`、`env.cueEnd(i)`、`env.len` 加上相对偏移推出，**不许写字面的秒数**（例如 `8.2`、`lt > 3.5`）。上游配音一变，字面时刻就全部错位。动作时长（如淡入 0.4 秒）可以写字面量，起点必须来自 `cue`。
- 校验会检查：整个镜头对任何 beat 都无反应是错误，个别 beat 无反应是警告。

## 确定性规则

- `draw` 必须是 `(lt, env)` 的纯函数：不依赖上一帧，不能有跨帧可变状态（不要在模块里累加计数器、不要缓存上一帧的结果）。
- 禁止：`Math.random`、`Date`、`performance.now`、`requestAnimationFrame`、`setTimeout`/`setInterval`、`fetch`、外部 URL、`eval`/`new Function`。需要随机时自己写带种子的伪随机函数（金样本里有 `rng(seed)`）：模块加载期可以用它生成静态数据（星点位置之类），渲染期不要再消耗随机数。
- 拿不到的东西就算出来：粒子位置用解析式（初速、阻力、重力）直接算，不要逐帧模拟。

## 画面规则

- **画面不重叠**：任何一帧上，两个对象的可读内容都不得互相压盖，文字不得出画。不重叠不会让校验失败，只会让观众看到一屏糊在一起的字——写代码时主动预防，预览拼图里要逐张检查。
- 镜头首尾要自然：不要在镜头边界留下半成品中间态；需要转场就用 `pad`，让前一镜头延后绘制、后一镜头提前绘制，合成器会按镜头顺序叠画。
- 一套统一的配色和视觉语言贯穿所有镜头，镜头之间有连贯的转场，不是几张 PPT。
- 字号：承载信息的文字不小于 40px；纯装饰的小标签（角标、编号）不小于 24px。更小的字在视频里读不出来。
- **不画字幕**：旁白文字不要作为字幕画在画面上（成片不叠字幕）。画面里的文字只用于标题、标签、公式等承载内容的元素。
- 字体只能用下面这些，写 CSS 字体名即可：`Anton`（英文大标题）、`Space Mono`（等宽小标签，400/700）、`Noto Sans SC`（中文，400/700）。中文标题和正文用 `Noto Sans SC`。项目风格目录 `style/fonts/*.woff2` 里的字体也可以用，字体名是文件名去掉扩展名。内置字体覆盖常用汉字，生僻字可能显示成方框，校验会警告。

