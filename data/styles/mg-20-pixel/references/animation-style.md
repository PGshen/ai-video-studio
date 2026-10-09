# 动画风格：像素风

风格全称：像素风 Pixel Art / 8-bit

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

低分辨率大颗粒像素 + 有限色板 + 低帧率精灵动画的复古游戏美学，在 B 站游戏区（MC、泰拉瑞亚、独立游戏）、8-bit 音乐 MV 和品牌怀旧营销中常见；Aseprite 教程在 B 站有 10 万+ 播放的稳定学习生态。
视觉特征 大颗粒像素与硬边缘, 有限色板(8~32色), 8~12fps 精灵帧动画, 抖动渐变 dithering, CRT 扫描线滤镜
关键技法 Aseprite 绘制精灵表（sprite sheet）+ 序列帧循环（走路 6~8 帧、呼吸 2~4 帧）
缩放必须最近邻插值（CSS image-rendering: pixelated），杜绝抗锯齿糊边
动画用 steps() 阶梯时序而非平滑缓动，保持逐帧感
视差卷轴背景：远中近三层不同速度整像素平移
可选 CRT 后处理：扫描线+桶形畸变+磷光辉光

## 原作的实现方式

320×180 的画布逐点绘制再放大，调色板轮换做出昼夜光线。

原作建议的技术路线：HTML Canvas at 320×180 internal resolution, integer-scaled ×6 with nearest-neighbour; sprites authored as pixel arrays in code; limited palette

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作就是 320×180 画布逐点绘制再放大，完全适合 Canvas 2D：先画到 320×180 的离屏画布，再 `imageSmoothingEnabled=false` 放大 6 倍到 1920×1080。坐标取整、阶梯式计时，精灵不用平滑缓动。像素中文字体本项目没有，需要的话用 Space Mono / Noto Sans SC 渲染到低分辨率画布再放大。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「像素冒险 PIXEL QUEST」A retro side-scroller title/attract sequence.
- Internal 320×180, ×6 nearest-neighbour; limited palette (PICO-8-like 16–32 colours) with dithered sky gradient; 3–4 parallax layers (sky, far mountains, mid forest/city, near ground tiles) moving by whole pixels.
- Hero sprite (hand-authored 16×16–24×24, 6–8 frame run cycle at ~10–12 fps) runs, jumps, collects coins (sparkle), bops a slime; the palette shifts day → sunset; a treasure chest opens with a light burst.
- Dialogue box with pixel CJK font typing 「欢迎来到像素世界！」; chunky pixel logo "PIXEL QUEST" drops in with shine sweep; optional CRT pass (scanlines, slight barrel, phosphor glow) that doesn't blur pixels into mush.
- Strictly: nearest-neighbour, integer pixel positions, stepped timing (no smooth easing on sprites).
Sound: chiptune (pulse lead, triangle bass, noise drums) + jump/coin/chest SFX.
