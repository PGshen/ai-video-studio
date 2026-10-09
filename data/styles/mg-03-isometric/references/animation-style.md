# 动画风格：等轴 2.5D

风格全称：等轴 2.5D Isometric / 2.5D

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

以 30° 等轴测投影展示微缩世界：小城市、办公室切片、数据机房，无灭点、处处等比。信息密度高又不失可爱，是科技公司架构图动画和 App 功能演示的标配。School of Motion 有专门的 isometric mograph 教程系列。
视觉特征 30°等角投影, 无透视灭点, 微缩场景, 楼房生长动画, 平行滑轨式运镜
关键技法 SSR 公式造等轴面：Scale 纵向 86.6% → Shear/skew ±30° → Rotate ∓30°，三个面分别做后拼合
假 3D 靠图层排序：Z 序=画面 y 坐标，物体沿等轴网格移动时保持 2:1 像素斜率
楼房'生长'：底面先落位，立面用 scaleY 从 0 拉起 + 顶面延迟 2~3 帧盖上
运镜是整组平移（无旋转），配合前中后景 1:0.8:0.6 的视差速度
AE 里可用真 3D 图层+正交相机（无透视）偷懒，Motion Design School 的 Isometric Camera 技巧即此路

## 原作的实现方式

Three.js 正交相机搭的等轴场景，所有模型和材质都在 js/ 里用代码生成。

原作建议的技术路线：HTML: Three.js OrthographicCamera at true isometric angle + soft shadows + AO (three/addons postprocessing), or SVG with SSR matrix faces

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作用 Three.js 正交相机。本项目只有 Canvas 2D：用等轴投影公式（x 轴 30°、y 轴 150°）手算方块三个面的多边形，按画家算法从后往前画；建筑「生长」= 墙面高度从 0 带过冲长到目标。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「微缩智慧城」An isometric miniature city / data campus that builds itself — the School-of-Motion isometric mograph showpiece.
- True isometric camera (orthographic, 35.264° elevation, 45° azimuth), no perspective, pastel studio palette (lavender ground, mint, peach, sky blue, white) with soft shadows + ambient occlusion so it reads like a premium Dribbble/Behance hero.
- 0–2s: ground tiles flip/drop in as a wave from the centre (tiny bounce each);
- 2–5s: buildings GROW — base lands, walls scaleY from 0 with overshoot, roof caps 2–3 frames later; trees pop; windows light up in sequence;
- 5–8s: life — cars loop along roads, a little train, drones carrying packets, glowing data streams pulse between buildings, a wind turbine spins; camera does parallel slides (no rotation) with 1 : 0.8 : 0.6 parallax layers (foreground clouds);
- 8–10s: pull back to reveal the whole island floating in a pastel void; title card set ON the isometric plane (text skewed into iso space) e.g. "SMART CITY OS".
Sound: bright plucky tech melody (FM marimba/pluck), soft clicks/pops for every tile/building landing, airy whoosh on the pull-back.
