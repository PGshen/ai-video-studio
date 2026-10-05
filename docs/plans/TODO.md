# 待办

记录**还没有写成计划**的工作：下一个里程碑、子项目、负责人交代的零散事项。
已经开工的工作看 `active/` 中的计划；技术债的细节写在 [tech-debt.md](../quality/tech-debt.md)，这里只放需要排期的条目并链接过去。

## 使用规则

- **会话开始**：`active/` 中没有计划时，从这里挑下一件事；有计划时以计划为准，这里只作参考。
- **新增**：负责人交代的、或执行中发现但不属于当前计划的事项，加到「待办」末尾，写明来源和日期。
- **开工**：条目写成计划后，在条目后标注计划文件名；计划完成后把条目移到「已完成」。
- **优先级**：P0 阻塞后续工作，P1 下一步要做，P2 有空再做。顺序和优先级由负责人决定，AI 可以建议，不自行调整。
- 每条一两行，细节放进设计文档、ADR、技术债或计划，这里只放链接。

## 待办

| 优先级 | 事项 | 来源 | 备注 |
|---|---|---|---|
| P1 | 多形态视频子项目 2：统一时间轴 + HTML 引擎 | [设计 §11](../design/2026-10-04-html-video-pipeline.md)，2026-10-04 | 设计 §12 的小试已于 2026-10-04 完成，结论可行，见 [html-canvas-agent-spike](../references/html-canvas-agent-spike.md)；设计已批准 [timeline-html-engine](../design/2026-10-04-timeline-html-engine.md)，拆为计划 2A/2B（均已完成）；子项目 2 整体完成 |
| P1 | 多形态视频子项目 3B：混音（含 sidechain）、`/music/*` api、`MusicCanvas`、预览音频、成片 | [synth-music-reel 设计](../design/2026-10-05-synth-music-reel.md)，2026-10-05 | 3A（agent 侧）已完成待验收，见 [synth-music-3a](active/synth-music-3a.md)；3B 计划还没写，3A 验收后再写 |
| P2 | 多形态视频子项目 4：导入音乐 + 音乐 MV | [设计 §11](../design/2026-10-04-html-video-pipeline.md)，2026-10-04 | 依赖子项目 3 |
| P2 | 把本地 `main` 推送到 `origin` | 2026-10-04 | 需负责人确认后再推 |
| P2 | 上游时间轴变化摘要（stale 后前言附段落增减与时长变化） | [timeline-html-engine §13](../design/2026-10-04-timeline-html-engine.md)，2026-10-04 | 子项目 2 有意延后 |
| P2 | 项目级分辨率与 fps 设置 | 同上 | 子项目 2 沿用 1920×1080、30fps |
| P1 | 3B 开工前修 3A 评审的 Minor：NaN/Inf 校验、`events.json` 的 `offset` 校验、工具返回文本字节上限、输出大小上限（`events.json`/stdout/`RLIMIT_FSIZE`）、"1分30秒"目标时长解析、`preexec_fn` 改法、`analysis.png` 原图是否会超 1 MiB（实测）、脚本快照、`to_thread`、越界写与压缩降质循环的测试 | 3A 整分支评审，2026-10-05 | 明细见 [synth-music-3a 决策记录](active/synth-music-3a.md) |
| P2 | manim 阶段 `render_preview` 返回的图片限制大小（≤ 400 kB JPEG，防 Claude SDK 单条消息 1 MiB 上限） | 3A 冒烟发现，2026-10-05 | 见 [claude-agent-sdk](../references/claude-agent-sdk.md) 末节；`stages/animation/render_preview.py:115` |
| P2 | 真实模型对 `animation/assets/*` 用法的验证 | 同上 | 子项目 2 的小试未覆盖 |

## 已完成

| 完成日期 | 事项 | 计划 |
|---|---|---|
| 2026-10-05 | 短片形态（`bt/bar/hit/energy`）与合成配乐的真实模型小试 | 无计划，见 [motion-reel-spike](../references/motion-reel-spike.md) |
| 2026-10-05 | 多形态视频子项目 2B：HTML 成片、实时预览与前端画布 | [html-engine-2b.md](completed/html-engine-2b.md) |
| 2026-10-05 | 多形态视频子项目 2A：统一时间轴 + HTML 引擎 + animation_html 阶段 | [html-engine-2a.md](completed/html-engine-2a.md) |
| 2026-10-04 | 修复 TD-64、TD-65（多上游定稿/stale 恢复） | 无计划，见 [tech-debt.md](../quality/tech-debt.md) 已处理 |
| 2026-10-04 | 多形态视频子项目 1：项目类型与按项目派生的阶段流水线 | [pipeline-config.md](completed/pipeline-config.md) |
