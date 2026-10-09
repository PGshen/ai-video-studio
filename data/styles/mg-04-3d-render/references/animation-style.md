# 动画风格：3D 渲染

风格全称：3D 渲染系（C4D/Blender 质感） 3D Render / CGI Motion Design

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

Cinema 4D + Redshift/Octane 或 Blender 渲染的实体质感动画：软胶、玻璃、金属、布料，配合克隆阵列和物理模拟。是高端产品片（手机、饮料、球鞋）和品牌 ident 的主流，Maxon 官方 Demo Reel 就是该风格的年度风向标。
视觉特征 PBR真实材质, 浅景深, 柔和棚拍布光, 克隆器阵列, 软体碰撞, 糖果色软胶质感
关键技法 MoGraph 核心：Cloner 克隆器 + Random/Plain Effector 做群体波浪式动画
质感三件套：SSS 次表面散射（软胶感）+ AO + HDRI 三点布光
运动多用长尾 ease：位移曲线前 20% 完成 80% 路程，收尾极慢，配 motion blur
24/25fps 电影帧率 + 浅景深（f/1.8 感）区别于 2D 系的 30fps 利落感
常见结构：产品为轴心，粒子/流体/布料围绕它做物理模拟编排

## 原作的实现方式

Blender Cycles 渲染：blender/sim.py 算出全部运动，scene.py 搭场景，render.py 出序列帧；index.html 再叠上文字和颗粒合成。序列帧体积大，没有收录。

原作建议的技术路线：Blender 5.1.2 CLI (bpy script → Cycles on Metal GPU with OIDN denoise, or EEVEE if it holds quality) → PNG sequence → ffmpeg; optional HTML overlay pass for typography

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作用 Blender Cycles 渲染，本项目做不到真 3D。在 Canvas 2D 里用径向渐变 + 高光椭圆 + 柔和投影伪造糖果质感的圆角药丸/球体阵列，阵列做波浪式起伏；主角字标用弹簧阻尼做挤压抖动落地；景深用离焦层 `filter: blur()` 近似。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「Soft & Satisfying」The C4D/Octane pastel product-ident look (Maxon demo-reel vibe): soft candy materials, cloner arrays, physics-feel motion.
- Pastel studio: infinite cyc backdrop, big soft area lights + HDRI (see /assets/hdri), shallow DOF (f/1.8 feel), 24 fps, real motion blur.
- A MoGraph-style cloner field (geometry-nodes grid of glossy rounded pills/spheres) ripples with an effector wave; a hero object — inflated/bevelled 3D wordmark (e.g. "SOFT" or an invented brand) or a glossy jelly logo — drops in, squash-and-stretch jiggle (damped spring), collides with and displaces the cloner field.
- Material trio: SSS gummy (candy pink / peach), glossy plastic (cream / lilac), frosted glass or chrome accent — with AO, soft reflections, subtle subsurface glow.
- Camera: long-tail ease (80% of the move in the first 20%), ends on a clean hero composition held ~1s.
Sound: ASMR-satisfying soft thuds, squishes, bubbly pops, airy cinematic pad; hits frame-synced to impacts.
