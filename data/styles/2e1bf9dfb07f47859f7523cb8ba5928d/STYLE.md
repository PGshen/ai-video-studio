---
name: 概念传记·纸上溯源
description: 从高完播率认知偏差知识短片抽象出的风格族：暖白书卷衬线视觉 + 概念传记四问叙事（显形/机制/现身/和解，钩子与锚点按选题形态选取）+ 5字/秒书卷节奏 + 连续画布五段骨架（零硬切）+ 增量书写动画。适合概念、效应、定律、认知偏差类知识选题。
category: 科普视频
---

# 概念传记·纸上溯源

从高完播率认知偏差知识短片抽象出的风格族：暖白书卷衬线视觉 + 概念传记四问叙事（显形/机制/现身/和解，钩子与锚点按选题形态选取）+ 5字/秒书卷节奏 + 连续画布五段骨架（零硬切）+ 增量书写动画。适合概念、效应、定律、认知偏差类知识选题。

这套风格从旧项目的风格模板「概念传记·纸上溯源」导入。下面列出每个文件的用途和读取时机；
选题阶段只需要读本文件。

| 文件 | 内容 | 什么时候读 |
|---|---|---|
| `references/narrative-blueprint.md` | 叙事蓝图 | 叙事阶段：动笔改 `narrative.json` 之前 |
| `references/color-scheme.md` | 配色方案 | 叙事阶段：动笔改 `narrative.json` 之前（画面描述要写明颜色）；动画阶段：写镜头代码之前 |
| `references/animation-style.md` | 动画风格 | 动画阶段：写镜头代码之前 |
| `exemplars/exemplar-1.json` | 金样本（镜头结构与旁白语感） | 叙事阶段：动笔改 `narrative.json` 之前 |

**旧格式提示**：`references/narrative-blueprint.md`、`exemplars/exemplar-1.json` 沿用了旧系统的镜头字段名（`scene_index`、`beat_index`、`description`、`estimated_duration_seconds` 等）。`narrative.json` 的字段一律以叙事阶段的系统提示词为准；这些文件只参考写法、旁白语感、信息密度和镜头节奏，不要照抄字段名。
