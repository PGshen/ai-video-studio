# 动画风格：赛博朋克·HUD

风格全称：赛博朋克 HUD / FUI Cyberpunk HUD / FUI (Fictional UI)

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

模拟科幻电影/游戏界面的抬头显示包装：青橙霓虹线框、目标锁定框、雷达扫描、数据流小字。在科技数码测评、游戏剪辑（赛博朋克2077、EVA 二创）、军事航天科普和 AI 产品演示中作为『科技感』的默认皮肤，B 站 AE HUD 案例教程播放量达 20 万。
视觉特征 青色/橙色霓虹线框, 目标锁定框与十字准星, 雷达/环形扫描 loop, 等宽小字数据流与打字机文字, 六边形网格与辉光
关键技法 线框生长：SVG stroke-dasharray/dashoffset 描边动画，元素按层级错帧展开
环形雷达：conic-gradient 扫描扇区旋转 loop + 目标点闪烁
数字滚动：随机数快速跳变 3~5 帧后落定真实值；文字打字机 + 光标闪烁
锁定框：四角括号从大到小收缩吸附目标（scale 1.4→1.0 + 快出缓入）
全局外发光（glow）+ 轻微色差 + 扫描线叠加统一质感

## 原作的实现方式

Three.js 线框地球 + Canvas 界面层 + 辉光后期，地图数据是 assets/land-50m.json。

原作建议的技术路线：HTML: SVG/Canvas FUI layers + Three.js wireframe hologram; seeded random data; glow/scanline post pass

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作是 Three.js 线框地球 + Canvas 界面层 + 辉光后期。界面层（六边形网格、旋转刻度环、雷达扫描、滚动数字、打字状态行）本来就是 Canvas 2D；线框地球改用正交投影手算经纬线；辉光在 `global.js` 的后期里用 `shadowBlur` 或叠一层模糊副本实现。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「目标锁定 TARGET ACQUIRED」Cyberpunk HUD / FUI, film-UI grade (Territory Studio-level density & restraint).
- Deep teal-black; cyan #00E5FF linework with orange/red #FF6A00 alert state; hex grid, concentric rotating rings with ticks, radar sweep (conic) with blips, data columns (monospace numbers rolling 3–5 frames then settling), typewriter status lines with cursor, sparkline graphs, a central Three.js wireframe hologram (globe or drone) with scanlines.
- Layered build-up: lines draw on in hierarchical staggered order → data comes alive → a target is found → lock brackets snap 1.4 → 1.0 (fast-out slow-in) → everything flips to alert orange with 'TARGET LOCKED / 目标锁定', coordinates "N31°14′ E121°29′".
- Glow, slight chromatic aberration, scanlines, restrained micro-glitches.
Sound: darksynth pulse + HUD beeps, scan sweeps, ascending lock-on tone, alarm on lock.
