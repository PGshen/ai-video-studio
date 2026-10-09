---
name: 像素风
description: 低分辨率大颗粒像素 + 有限色板 + 低帧率精灵动画的复古游戏美学，在 B 站游戏区（MC、泰拉瑞亚、独立游戏）、8-bit 音乐 MV 和品牌怀旧营销中常见；Aseprite 教程在 B 站有 10 万+ 播放的稳定学习生态。
category: MG 动态设计
---

# 像素风（Pixel Art）

低分辨率大颗粒像素 + 有限色板 + 低帧率精灵动画的复古游戏美学，在 B 站游戏区（MC、泰拉瑞亚、独立游戏）、8-bit 音乐 MV 和品牌怀旧营销中常见；Aseprite 教程在 B 站有 10 万+ 播放的稳定学习生态。

这套风格来自开源合集「15 种 MG 动态设计风格」（[https://vincentwei1021.github.io/mg-styles-15/?lang=zh](https://vincentwei1021.github.io/mg-styles-15/?lang=zh)，源码与提示词 [https://github.com/vincentwei1021/mg-styles-15](https://github.com/vincentwei1021/mg-styles-15)，MIT 许可）。原作是一支 10 秒的 MG 品牌片（横屏 16:9（1920×1080），30 fps，片名「PIXEL QUEST 像素冒险」），每支都由 AI 按一份提示词写代码生成。

**用于本项目的提示**：原作是品牌短片，没有旁白叙事；这里只借它的**视觉语言和动效手法**（配色、标志性特征、关键技法），镜头结构、时长和旁白以本项目的叙事和时间轴为准。原作的技术路线（Three.js / WebGL / Blender / SVG）在本项目里都要改成 Canvas 2D 实现，见 `references/animation-style.md` 的「迁移要点」；原作用到的字体本项目没有，用动画阶段提示词允许的字体替代。

下面列出每个文件的用途和读取时机；选题阶段只需要读本文件。

| 文件 | 内容 | 什么时候读 |
|---|---|---|
| `references/color-scheme.md` | 配色方案 | 叙事阶段：动笔改 `narrative.json` 之前（画面描述要写明颜色）；动画阶段：写镜头代码之前 |
| `references/animation-style.md` | 动画风格：标志性特征、关键技法、原片创意、迁移要点 | 动画阶段：写镜头代码之前；叙事阶段需要构思画面时可参考 |
| `references/source-prompt.md` | 原作的完整提示词（英文，含工艺清单） | 需要细节时再看，不必每轮读 |
