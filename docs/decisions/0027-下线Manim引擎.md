# 0027：下线 Manim 引擎，老 manim 项目只读

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已采纳 |
| 日期 | 2026-10-09 |
| 相关 | [remove-manim 计划](../plans/active/remove-manim.md)、[架构设计](../design/2026-09-26-architecture.md) §4–§5 的 `animation` 阶段与 manim 渲染、[ADR 0005](0005-渲染并入动画阶段.md)、[ADR 0015](0015-成片整体渲染.md)、[ADR 0020](0020-阶段流水线按项目配置派生.md)、[ADR 0021](0021-HTML引擎与配乐阶段.md) |

## 背景

讲解视频最初只有 Manim 引擎（M2）。HTML 引擎（子项目 2A/2B）上线后，实际制作都走 HTML 讲解、动态图形短片和音乐 MV，Manim 讲解基本不用。Manim 却是安装成本最高的部分：Python 包 `manim` 连带二十多个依赖（pycairo、manimpango、moderngl、pyglet、skia-pathops、av 等），还要求系统装 cairo、pango、pkg-config 和 LaTeX；代码里也有一整套只服务它的阶段、引擎、worker 分支和测试夹具。

本地数据里只剩两个 manim 项目，其中一个是可删除的验证项目。

## 决定

- 新项目不再提供 Manim：`stages.pipeline` 的 `valid_kinds()`/`PRESETS` 只剩 HTML 引擎（5 种配置、3 张类型卡片）；创建请求带 `engine=manim` 返回 422；不带类型字段时默认 HTML 讲解（`DEFAULT_KIND`）。
- 删除 `stages/animation/`（`validate_scenes`、`render_preview`、提示词）、`engines/render/manim/`、`engines/render/base.py`（只服务 manim 的引擎协议）、worker 的 manim 渲染路径、前端 `AnimationCanvas.vue`；`manim`、`pyflakes` 依赖移除。
- 老 manim 项目（`engine=manim`，或没有类型字段、按 `LEGACY_KIND` 解析）**保留为只读**，不做数据迁移：
  - 照常列出、读取设置，选题和叙事可以查看；历史会话可以阅读。
  - `animation` 阶段不再注册：新建会话、发消息、继续、渲染成片、成片定稿都返回 409（`api.animation_stage.MANIM_RETIRED_DETAIL`）；worker 遇到这类任务直接以"Manim 已下线"失败；镜头检查一律"未检查"；前端在该阶段只显示下线提示。
  - `stage_default_profile` 里已存的 `animation` 键读时丢弃，写入时按未知阶段拒绝。
- `Engine`/`VideoKind` 类型仍保留 `manim`/`explainer_manim` 字面量，只用于解析和展示已存的老项目。

已批准的设计文档不改；其中 Manim 相关的章节（`animation` 阶段、manim 渲染与缓存、ADR 0005/0015 里 Manim 专属的部分）由本 ADR 取代。

## 考虑过的其他方案

- **把老项目迁移成 HTML 讲解**（改 `settings`、把 `animation` 阶段行改成 `animation_html` 并重开）：不选，负责人选择只读；只有两个项目，迁移脚本和旧 `.py` 场景的处理不值得。
- **直接删掉老项目，代码不再兼容没有类型字段的项目**：不选，会让历史数据在读取时被当成损坏。
- **保留 Manim 作为可选依赖（extras）**：不选，代码和测试的维护成本仍在，而实际不用。

## 影响

- 新环境只需要 uv、Node/pnpm、ffmpeg 和 Playwright 的 Chromium；后端依赖少了 25 个包。
- 以后重新引入类似的代码渲染引擎，需要重新设计阶段与 worker 分支；`docs/references/manim.md` 只作历史参考。
- 测试里的叙事夹具（`tests/fixtures/animation/` 的 narrative/timing/音频）仍被 HTML、配乐等种子共用；`fixtures/animation/seed.py` 改为老 manim 项目种子，用来覆盖只读行为。
