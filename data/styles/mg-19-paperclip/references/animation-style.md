# 动画风格：贴纸风·科普

风格全称：粗描边贴纸人科普 MG（回形针/林超风格） Bold-outline Sticker Explainer MG (PaperClip / Lin Chao style)

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

回形针 PaperClip 带火的知识区标准包装：实拍图片抠图后加粗白描边变成『贴纸』，与扁平图标、数据图表一起铺在大画布上，镜头平移缩放串联信息点；林超等财经/跨学科 UP 主将其与手写板书、公式卡片结合。至今仍是硬核科普、财经知识区、企业宣传片的主流范式。
视觉特征 照片贴纸化（粗白描边）, 蓝灰/米白冷静底色, 扁平图标+精确数据图表, 大画布镜头平移缩放, 信息密度极高的节拍化叙事
关键技法 素材照片抠图 + 8~12px 白描边统一质感，消除图片来源差异
超宽大画布布局，摄像机层做平移/缩放（ease 长曲线），一镜串多个信息点
图表动效：柱状图生长、数字滚动计数、路径描边生长
解说词逐句驱动画面元素入场，语速快、每句必有新视觉元素
克制配色（2~3 色）+ 等线字体，保持『严肃感』

## 原作的实现方式

一张超大画布配相机运镜，图表用 D3 + TopoJSON 画，贴纸由 tools/stickers.py 抠图描边。

原作建议的技术路线：HTML: one huge canvas (e.g. 6000×3000 px) with a camera transform (long eases), SVG charts, photo stickers with 10px white outline

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

**最贴近本项目知识视频的一套。** 原作是超大画布 + 相机运镜，图表用 D3 + TopoJSON。Canvas 2D 里用全局相机变换（`translate/scale`）在一张大画布上连续运镜；柱状图、计数滚动、引线标注都手写；地图可以改成简化示意图。每一拍都引入一个新的视觉元素。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「回形针式硬核科普」The PaperClip-style knowledge-video look: sticker-ized photos + flat icons + precise charts on a giant canvas with continuous camera moves.
- Topic (write your own tight copy), e.g. 「一部手机里，藏着多少种元素？」.
- Calm blue-grey/off-white canvas (#E9EEF2 + slate), 2–3 colours + one accent (e.g. #FF5A36); equal-weight sans typography, strict alignment.
- One continuous camera path: sticker phone photo (white 10px outline, soft shadow) → exploded-parts stickers with leader-line labels → periodic-table grid where element tiles light up → bar chart grows with count-up "70+" → world map with supply routes drawing → pull out to a bold typographic title card in the 回形针 manner (heavy sans, huge number, small caption).
- Every beat introduces a new visual element; charts are exact (bars to scale, numbers consistent).
Sound: clean tech-explainer bed, UI clicks, ticking during count-up, soft whoosh on camera moves.
