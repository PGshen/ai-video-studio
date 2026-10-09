# 动画风格：扁平矢量

风格全称：扁平矢量动画 Flat / Vector 2D Motion Graphics

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

MG 动画最主流的基本盘风格，源自 Google Material/企业解释视频（explainer）传统。纯色几何化的人物与场景、无描边或极简描边、大色块撞色，一切元素都是矢量形状。常见于 SaaS 产品宣传、科普解说、企业年报视频。
视觉特征 纯色大色块, 几何化角色, 无渐变或极少渐变, 干净留白, 高饱和品牌色板, 元素弹性入退场
关键技法 AE Shape Layer + 父子级 null 控制层级，人物四肢用锚点旋转做 rig
弹性缓动是灵魂：overshoot 用 cubic-bezier(0.34,1.56,0.64,1) 或 AE 里 70~85% influence 的贝塞尔手柄；入场'预备-冲出-回弹'三段式
元素错峰入场（stagger 2~4 帧），同一时刻只让一个主体动
30fps 居多；位移动画带 10% 左右 squash&stretch 增加弹性
转场常用色块擦除（shape wipe）或元素飞出带动整场切换

## 原作的实现方式

一个 HTML 页面，SVG 图形 + 手写缓动，按时间逐帧画出。

原作建议的技术路线：HTML: SVG + GSAP (CustomEase/CustomBounce/MorphSVG); motion blur mb=4 for fast moves

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作是 SVG + 手写缓动，可直接改写成 Canvas 2D 路径。一次只让一个主角动；挤压拉伸约 10%；转场由元素带出（形状擦除），不用交叉淡化。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「一镜到底的扁平世界」One-continuous-shot brand explainer, the canonical Motion-Ocean/Google-explainer form, pushed to showreel polish.
- 0.0–1.2s HOOK: empty bold color field; a single saturated circle drops in with the three-phase anticipation → stretch → squash → overshoot → settle. Immediately readable craft.
- 1.2–3.0s: the circle becomes the sun; a flat city pops up building-by-building with 2–4 frame stagger (each with its own mini overshoot), clouds slide, birds flap.
- 3.0–5.5s: camera pushes into one window → a geometric character at a desk (limb rig with anchor rotations, head bob, blink) reacts; phone pings.
- 5.5–8.0s: the notification bubble expands to fill the frame as a SHAPE WIPE transition; inside, icons burst in a choreographed rhythm (bar chart grows, check mark draws, heart pops, coin flips).
- 8.0–10.0s: element-driven transition — everything collapses/flies into a logo lockup for an invented brand (e.g. "Popwise") + tagline, elastic settle, 1s hold with micro-motion.
Rules: one hero moves at a time; squash&stretch ~10%; secondary action & follow-through; element-driven transitions (an object flies out and carries the cut); strictly flat (no gradients), bold 5–6 color palette (e.g. ultramarine #2B2BFF, coral #FF5A4E, sunflower #FFC62B, mint #2EE6A8, cream #FFF6E9, ink #151433).
Sound: upbeat future-bass/pop ~120 BPM; pop/boing/whoosh on each entry, synced to the frame.
