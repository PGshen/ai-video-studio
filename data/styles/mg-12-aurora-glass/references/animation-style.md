# 动画风格：弥散渐变·玻璃拟态

风格全称：弥散渐变 / 玻璃拟态 Gradient Blur (Aurora) & Glassmorphism

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

大面积高斯模糊的彩色光斑（aurora/mesh gradient）缓慢漂移作底，磨砂半透明玻璃卡片浮在其上。苹果 iOS 26 Liquid Glass 与各家 AI 产品发布把这一风格推成 2024-2026 科技品牌片的默认视觉，气质是'慢、透、高级'。
视觉特征 大色斑高斯模糊漂移, 磨砂玻璃卡片, 1px高光描边, 邻近色低对比配色, 缓慢呼吸感节奏
关键技法 底层 aurora：3~5 个纯色大圆 blur 80~150px，各自沿贝塞尔路径 20~40 秒漂移循环，彼此 blend 出 mesh gradient 感
玻璃卡片配方：backdrop-filter blur(20~40px) + 白色 5~10% 填充 + 1px 白色 30% 内描边 + 大半径圆角
配色用邻近色 2~3 色（紫蓝青/橙粉红），撞色会脏；暗底亮斑比亮底更出效果
全局叠 3~5% 噪点防 banding（与颗粒质感技法交叉）
缓动接近 linear 或 sine 呼吸曲线，一切都慢——快动作会立刻破坏气质；文字入场也只用 opacity+8px 位移

## 原作的实现方式

WebGL2 着色器画极光和玻璃折射（shaders.js），界面用 Canvas 画。音频脚本会顺带写出 out/env.json，让画面上的声波跟着音乐动。

原作建议的技术路线：HTML WebGL: aurora mesh-gradient shader + glass refraction (SDF lens, chromatic dispersion) + DOM/CSS backdrop-filter glass cards

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作用 WebGL2 着色器画极光和玻璃折射。Canvas 2D 里极光用大半径径向渐变叠加（`globalCompositeOperation='screen'`）；玻璃卡片用 `ctx.filter='blur(30px)'` 把背景裁剪进卡片区域重画；透镜放大用裁剪 + 缩放重画背景近似。全程正弦 / 呼吸式缓动，不要快。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「Liquid Glass」2025–26 AI-product-launch aesthetic: slow, translucent, expensive.
- Deep indigo-black base; 4–5 aurora blobs (violet/blue/cyan/magenta, adjacent hues only) drifting on bezier paths, blending into a mesh gradient, 3–5% noise dithering (no banding).
- Frosted glass cards (backdrop blur ~30px, 5–10% white fill, 1px 30% white inner highlight, large radius) float in with parallax depth and slight 3D tilt; micro-UI inside (chat bubble, voice waveform, toggles) animates with opacity + 8px rise.
- WOW: a Liquid-Glass lens (true refraction, chromatic dispersion on the rim, specular edge) glides across and magnifies the aurora and the cards.
- Title (invented product, e.g. "Aurora — think in light") in a light elegant sans; sine/breathing easing everywhere; nothing fast.
Sound: ambient cinematic pad, soft shimmer, very subtle UI ticks.
