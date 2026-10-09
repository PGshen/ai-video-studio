# 动画风格：拼贴剪贴

风格全称：拼贴剪贴 Collage / Cutout Animation

## 标志性特征与关键技法（判断是否「像这个风格」的依据）

把老照片、报纸、手撕纸片剪出来重新拼装的复古超现实风格，源头是 Monty Python 和苏联构成主义海报。人物头身比例失衡、嘴巴单独开合、半调网点纹理是标志。近年与'杂志风'合流，成为音乐类、街头潮流类短视频的高频风格。
视觉特征 照片剪影白描边, 半调网点, 报纸纹理, 比例失衡的超现实拼装, 定格式抽帧运动
关键技法 素材处理：人物/物件抠图后加 2~4px 白描边（剪刀剪出来的感觉）+ 半调 halftone 滤镜
关节动画：锚点设在肩/肘/颌，做 puppet 式分段旋转，嘴巴用两三张替换帧开合
刻意降帧：主体运动 12fps 甚至 6fps（stop-motion 感），位置加 ±2px 随机抖动模拟手摆
图层结构：背景纸纹 → 大形色块 → 照片剪影 → 手写涂鸦/胶带贴纸 → 颗粒调整层
转场用'手把元素拍上来'或整页翻纸

## 原作的实现方式

公有领域的老照片和版画剪成素材（work/ 里的脚本），在 HTML 里按 12 fps 逐格拼贴。

原作建议的技术路线：HTML: DOM/Canvas with PNG cutouts from /assets/images (rembg), SVG/CSS white-edge + halftone filters; stepped 12 fps (render 30 fps, hold motion on 12 fps grid)

## 迁移要点（本项目动画阶段：Canvas 2D、画面是时间的纯函数）

原作用公有领域图片剪成素材、按 12 fps 逐格拼贴。本项目可把剪好的 PNG 放进 `animation/assets/`；运动按 12 fps（定格处 6 fps）取整时间，叠加 ±2px 手放抖动；转场用撕纸或翻纸。

通用约束：
- 只用带种子的随机数，粒子和物理用解析式或预计算，任意时刻 t 都能直接画出一帧。
- 原作的「钩子 → 递进 → 高潮（约 60–75% 处）→ 定格收尾」节奏，在本项目里落到每个镜头和整片上：镜头开头 0.5 秒内要有东西动，收尾定格时保留细微的活动。
- 转场由元素带出，不用交叉淡化（除非这套风格本身就以柔和淡入淡出为特征）。

## 原片创意（英文原文，供参考，不要照抄故事和品牌名）

「脑洞拼贴」Surreal Dada/Monty-Python cutout collage in a modern editorial magazine finish.
- Newsprint/kraft paper ground; a public-domain Victorian portrait cutout with rough white scissor edge + halftone; the top of the head FLIPS OPEN like a lid (Terry Gilliam homage) revealing deep space (NASA PD imagery) from which flowers, birds, planets, pointing hands and a vintage rocket spill out.
- Jaw/mouth on a separate cut flaps with the sound; hands slap elements onto the page; torn-paper strips; bold constructivist red/black diagonal typography (e.g. "THE MIND IS A COLLAGE" / 脑洞大开).
- Motion on 12 fps (even 6 fps for some holds) with ±2px hand-placement jitter; paper-flip / torn-paper transition to the end card.
Sound: vinyl crackle, jazzy boom-bap bed, paper rustles, scissors snips, slaps and a comic 'pop' when the lid opens.
