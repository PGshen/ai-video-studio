# 动画风格：线条动画

风格全称：线条动画 Line Art / Line Animation

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

以单色细线为唯一造型语言，线条自我描绘（draw-on）、延伸、转折并变形为下一个图形，一笔连成整支片子。极简高级感强，常见于奢侈品、金融、建筑类品牌片和 logo 动画。
视觉特征 等宽细线, 单色或双色, 大量负空间, 线条连续生长, 线面转换瞬间
关键技法 核心是 stroke 描绘：AE 用 Trim Paths 0→100%，Web 端用 SVG stroke-dasharray/dashoffset
线宽全片恒定（2~4px），转角处让描绘速度略减速，用 easeInOut cubic-bezier(0.65,0,0.35,1)
'一笔画'叙事：上一图形的尾线即下一图形的起线，路径提前在 Illustrator 里连好
线转面：描完轮廓后用同路径的 fill 从锚点扩展填充
配合微小的端点圆头（round cap）与路径抖动可增加手绘感

## 原作的实现方式

一条 SVG 路径贯穿全片，描边进度由 film.js 按时间计算。tools/ 里的脚本从路径算出转角和速度，给配乐卡点。

原作建议的技术路线：HTML: SVG paths + stroke-dashoffset (getTotalLength) + GSAP; a virtual camera that follows the pen tip

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作是一条 SVG 路径 + 按时间算描边进度。Canvas 2D 用 `setLineDash` / 路径长度采样实现描边生长；拐角处减速（cubic-bezier(0.65,0,0.35,1)）；虚拟镜头跟随笔尖用 `ctx.translate/scale` 实现。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「一笔画」One-line narrative for a luxury / architecture brand — the whole film is ONE continuous line.
- Deep midnight ground (#0B1320 or near-black) + a single champagne-gold line (#E9D7A5), constant ~3px, round caps, a softly glowing pen tip that leads the draw.
- Story (continuous path, the tail of each figure is the start of the next): a seed → sprouts into a sapling → branches become the structural lines of a building → the building outline extends into a skyline/horizon → the horizon line lifts and loops into a monogram logo → LINE-TO-FILL moment (logo fills with gold from its anchor) → thin letter-spaced serif wordmark (e.g. "ATELIER LINEA") fades up.
- Draw speed eases into corners (cubic-bezier(0.65,0,0.35,1)); the virtual camera drifts/pushes to keep the tip in frame, then dollies out at the end to reveal the whole drawing composed as a poster; older line segments dim to ~35% as the camera moves on.
Sound: minimal felt piano + soft string swell; a pen-on-paper whisper whose loudness follows tip speed; delicate chime on the fill.
