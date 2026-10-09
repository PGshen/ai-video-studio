# 动画风格：几何构成·包豪斯

风格全称：几何构成 / 包豪斯 Geometric / Bauhaus Motion

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

圆、三角、矩形在严格网格上做精确的平移、旋转、缩放，三原色+黑白的限定色板，机械理性的秩序美。源自包豪斯与瑞士国际主义平面传统（Adobe 曾与 Bauhaus 档案馆合作 Hidden Treasures 项目），也是动态海报（kinetic poster）的主流语言，与音乐节拍天然合拍。
视觉特征 基础几何形, 红黄蓝黑限定色, 严格网格对齐, 旋转以几何中心为轴, 节拍驱动的模块化运动
关键技法 一切运动锚定网格：位移距离=网格模数整数倍，落点必在网格线上
缓动克制：easeInOutQuad 或干脆匀速，禁用 overshoot——机械感是特征不是缺陷
节拍驱动：每个几何元素在节拍点瞬时出现/翻转，一拍一个动作，类似我们已做的卡点逻辑
旋转轴心玩法：绕自身中心、绕边缘顶点、绕画面中心三种交替制造韵律
生成式变体：Processing/p5.js 用三角函数相位差批量驱动几何阵列（国内动态海报圈主流做法）

## 原作的实现方式

120 px 网格上的几何图形，film.js 按 120 BPM 的节拍逐拍搭建。

原作建议的技术路线：HTML: SVG/Canvas + GSAP on a strict modular grid, beat grid at 120 BPM

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作是 120px 网格上的几何图形、按 120 BPM 逐拍搭建，本来就适合 Canvas 2D。本项目没有固定 BPM：把「拍」换成旁白 beat，每个 beat 一个模块动作（四分之一圆绕角旋转 90°、半圆滑一格、三角翻转、方块切分）；位移取整数个模块；缓动 power2.inOut 或线性，不要过冲。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「包豪斯动态海报」Bauhaus 1919 kinetic poster — mechanical, rational, musical.
- Cream paper (#F1E9DA), primaries red #E03C31, yellow #F2B705, blue #1E4FA3, black #111; strict modular grid (e.g. 240px modules); every move is an integer number of modules; every landing on a grid line.
- 120 BPM (0.5 s/beat): each beat a module acts — quarter circles rotate 90° about a corner pivot, semicircles slide one module, triangles flip, squares split; rotation pivots alternate (own centre / corner / frame centre).
- 0–2s grid lines draw & the first red circle lands; 2–6s the composition assembles into a Kandinsky/Bauhaus poster; 6–8s phase-shifted cascade wave across the grid on the drop; 8–10s freeze into a perfect poster with Swiss typography: "BAUHAUS" set vertically in heavy geometric sans + small caps "FORM · FARBE · FUNKTION".
- Easing: power2.inOut or linear — NO overshoot; subtle paper tooth + slight print misregistration allowed.
Sound: minimal techno/click — each flip = a pitched click/blip, kick on quarters.
