# 待办

记录**还没有写成计划**的工作：下一个里程碑、子项目、负责人交代的零散事项。
已经开工的工作看 `active/` 中的计划；技术债的细节写在 [tech-debt.md](../quality/tech-debt.md)，这里只放需要排期的条目并链接过去。

## 使用规则

- **会话开始**：`active/` 中没有计划时，从这里挑下一件事；有计划时以计划为准，这里只作参考。
- **新增**：负责人交代的、或执行中发现但不属于当前计划的事项，加到「待办」末尾，写明来源和日期。
- **开工**：条目写成计划后，在条目后标注计划文件名；计划完成后把条目移到「已完成」。
- **已批准、暂缓执行的计划**放在 `todo/`：负责人决定开工时移到 `active/`，状态从「已批准（暂缓）」改为「执行中」。
- **优先级**：P0 阻塞后续工作，P1 下一步要做，P2 有空再做。顺序和优先级由负责人决定，AI 可以建议，不自行调整。
- 每条一两行，细节放进设计文档、ADR、技术债或计划，这里只放链接。

## 待办

| 优先级 | 事项 | 来源 | 备注 |
|---|---|---|---|
| P1 | 多形态视频子项目 2：统一时间轴 + HTML 引擎 | [设计 §11](../design/2026-10-04-html-video-pipeline.md)，2026-10-04 | 设计 §12 的小试已于 2026-10-04 完成，结论可行，见 [html-canvas-agent-spike](../references/html-canvas-agent-spike.md)；设计已批准 [timeline-html-engine](../design/2026-10-04-timeline-html-engine.md)，拆为计划 2A/2B（均已完成）；子项目 2 整体完成 |
| P1 | 原生支持 Windows（Windows 上能用也能开发） | 负责人，2026-10-08 | 设计已批准：[windows-native-support](../design/2026-10-09-windows-native-support.md)；计划执行中：[windows-native.md](active/windows-native.md)（2026-10-09 在 Windows 电脑上开工） |
| P2 | 音乐 MV 的画面质量：让用户通过对话与风格库控制要生成什么样的动画 | 负责人试看 4B 冒烟成片的反馈，2026-10-06 | 4B 冒烟成片（agent 自主写的画面）效果一般；方向是让对话与风格库更强地约束画面（风格、母题、镜头语言），而不是让 agent 自由发挥。负责人系统使用后再提具体需求；强拍相位/BPM/淡出的试听核对也一并在那时做（见 [import-music-mv.md](../references/import-music-mv.md)） |
| P2 | 讲解类（`explainer`）是否也取消阶段拆分（`topic → narrative → music → animation_html`） | produce 阶段设计，2026-10-06 | 短片、MV 合并配乐与动画后效果是否更好，负责人试用后再决定；讲解类有旁白与时间戳，耦合方式不同，不一并改 |
| P2 | 能量曲线叠加歌词刻度 | mv-lyrics T6，2026-10-07 | 歌词列表已能点击跳转；刻度要改 `EnergyView` 的坐标层，用过之后再决定要不要 |
| P2 | 上游时间轴变化摘要（stale 后前言附段落增减与时长变化） | [timeline-html-engine §13](../design/2026-10-04-timeline-html-engine.md)，2026-10-04 | 子项目 2 有意延后 |
| P2 | 项目级分辨率与 fps 设置 | 同上 | 子项目 2 沿用 1920×1080、30fps |
| P2 | 真实模型对 `animation/assets/*` 用法的验证 | 同上 | 子项目 2 的小试未覆盖 |
| P3 | 运行时启动失败时界面上的错误信息是空的（`CLIConnectionError: Failed to start Claude Code:` 后面没有原因，原因只在 api 日志里） | windows-native T11，2026-10-10 | 把底层异常（如 `NotImplementedError`、找不到 CLI）带进 turn 的 `error` |
| P3 | 前端偶发 `Unhandled rejection: TypeError: Cannot read properties of undefined (reading 'find')` | windows-native T11，2026-10-10 | 在选题页建卡片/建项目时 vite 日志里出现一次，界面无可见异常，未复现 |
| P3 | Fake 运行时关闭时，新建会话的模型下拉框仍把 `fake` 标为默认 | windows-native T11，2026-10-10 | 本机曾用开了 Fake 的 `preview_start` 起过 api，种子里写进了 `fake`；`tasks.py dev`（不开 Fake）下默认仍选它，选了会失败 |

## 已完成

| 完成日期 | 事项 | 计划 |
|---|---|---|
| 2026-10-09 | 下线 Manim 引擎：删除 manim 阶段、渲染引擎与依赖（少 25 个包），老 manim 项目只读（ADR 0027） | [remove-manim.md](completed/remove-manim.md) |
| 2026-10-07 | 音乐 MV 的歌词联动（上传 LRC、歌词意象、`env.lyric`） | [mv-lyrics.md](completed/mv-lyrics.md) |
| 2026-10-07 | 配乐与动画合并阶段 `produce`（短片、MV 改为 `concept → produce`）+ 修复 1 MiB 消息缓冲区问题 | [produce-stage.md](completed/produce-stage.md) |
| 2026-10-06 | 多形态视频子项目 4B：上传、画布、预览与成片（导入音乐 + 音乐 MV，子项目 4 整体完成） | [import-music-4b.md](completed/import-music-4b.md) |
| 2026-10-05 | 多形态视频子项目 4A：导入音乐 + 音乐 MV（agent 侧） | [import-music-4a.md](completed/import-music-4a.md) |
| 2026-10-05 | 3A 整分支评审遗留的 Minor：NaN/Inf 与 `offset` 校验、工具文本与输出大小上限、`ulimit` 取代 `preexec_fn`、脚本快照、分析移出事件循环、"X分Y秒"解析、`analysis.png` 调色板压缩 | 无计划，见 [synth-music-3a 决策记录](completed/synth-music-3a.md) |
| 2026-10-05 | 3B 评审遗留的 Minor（`stale` 也比 wav 哈希、哈希按 (mtime, size) 缓存、成片混私有拷贝、`final.json` 新增 `music_hash`）；manim 预览图片限制大小（共用 `stages.common.picture`，JPEG ≤ 400 kB、同一条结果总预算 600 kB） | 无计划，见 [claude-agent-sdk](../references/claude-agent-sdk.md) 末节 |
| 2026-10-05 | 多形态视频子项目 3B：成片混音、配乐 api 与前端（子项目 3 整体完成） | [synth-music-3b.md](completed/synth-music-3b.md) |
| 2026-10-05 | 多形态视频子项目 3A：合成配乐 + 动态图形短片（agent 侧） | [synth-music-3a.md](completed/synth-music-3a.md) |
| 2026-10-05 | 短片形态（`bt/bar/hit/energy`）与合成配乐的真实模型小试 | 无计划，见 [motion-reel-spike](../references/motion-reel-spike.md) |
| 2026-10-05 | 多形态视频子项目 2B：HTML 成片、实时预览与前端画布 | [html-engine-2b.md](completed/html-engine-2b.md) |
| 2026-10-05 | 多形态视频子项目 2A：统一时间轴 + HTML 引擎 + animation_html 阶段 | [html-engine-2a.md](completed/html-engine-2a.md) |
| 2026-10-04 | 修复 TD-64、TD-65（多上游定稿/stale 恢复） | 无计划，见 [tech-debt.md](../quality/tech-debt.md) 已处理 |
| 2026-10-04 | 多形态视频子项目 1：项目类型与按项目派生的阶段流水线 | [pipeline-config.md](completed/pipeline-config.md) |
