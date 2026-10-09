# 动画风格：形变动画

风格全称：形变动画 Morphing / Shape Morph

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

一个图形丝滑连续地变成另一个图形：手机变成地图钉、咖啡杯变成落日。是图形叙事（visual storytelling）的核心语法，苹果发布会动效和高端 explainer 里最见功力的部分。
视觉特征 轮廓连续过渡无跳变, 中介形状桥接, 形变伴随位移旋转, 变形瞬间的挤压拉伸
关键技法 路径对齐是前提：两形状顶点数一致、首顶点方位对应（AE 里重设 first vertex），否则会打结
复杂 A→B 不直接变：先收敛为中介简形（圆/胶囊）再展开，'A→圆→B'两段各 8~12 帧
形变全程叠加 10~15% squash & stretch 与轻微旋转，掩盖插值的机械感
速度曲线中段最快 cubic-bezier(0.7,0,0.3,1)：起止各留 3 帧缓冲
Web 端用 flubber/polymorph 库做最优顶点匹配插值，效果远好于朴素 SMIL

## 原作的实现方式

SVG 形状逐点插值，字标轮廓由 tools/glyphs.py 从字体里提取成 glyphs.json。

原作建议的技术路线：HTML: SVG + flubber or GSAP MorphSVGPlugin (tune shapeIndex), color-field wipes

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作是 SVG 逐点插值。Canvas 2D 同理：把每个图标重采样成相同点数的闭合多边形，A→B 中间先经过圆形/胶囊，叠加旋转与 10–15% 挤压拉伸；检查每次变形中点的静帧，不能打结。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「万物相连」Apple-keynote-grade morph chain: one hero shape continuously becomes 6–8 meaningful icons, on the beat.
- Chain example: coffee cup → (circle) → sun → sunset over sea → gull → paper plane → location pin → heart → invented brand logo "morphe" with wordmark.
- Every A→B goes through a simple intermediate (circle/capsule) with rotation and 10–15% squash&stretch; sub-parts morph in sync (steam → sun rays → waves).
- Background color fields change with each morph (clean color-block wipes); ease cubic-bezier(0.7,0,0.3,1), 3-frame cushions at start/end; no knotting/tangling ever (check every morph mid-point stills).
Sound: rhythmic plucky arpeggio; a pitched whoosh per morph landing on the beat.
