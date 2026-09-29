# 旧项目资产迁移清单

旧项目的绝对路径：`/Users/peng/Me/Ai/ai-video`（下文简写为 `../ai-video`）。**只读**，不修改旧项目中的任何文件。

迁移方式：复制到新位置后，按新架构改写（去掉对旧 settings、db、storage 的依赖），**同时迁移或改写对应的测试**。新代码不 import 旧代码。迁移完成后更新本表的状态。

| 资产 | 旧路径 | 新位置 | 旧测试 | 里程碑 | 状态 |
|---|---|---|---|---|---|
| manim 渲染引擎（代码预处理、静态检查、镜头合并、渲染） | `../ai-video/backend/app/engines/render/manim.py`、`base.py` | `backend/src/studio/engines/render/` | `tests/test_manim_render_engine.py` | M2 | 未开始 |
| 引擎约束提示词 | `../ai-video/backend/app/engines/ai/engine_specs/manim.yaml` | `backend/src/studio/stages/animation/` | — | M2 | 未开始 |
| 代码规则 | `../ai-video/backend/app/codegen_rules.py` | `backend/src/studio/stages/animation/` | — | M2 | 未开始 |
| 镜头校验（沙箱写入、读取、校验） | `../ai-video/backend/app/services/strategies/agent_sandbox.py` | `stages/animation/` 中的 `validate_scenes` 工具 | `tests/test_agent_sandbox.py` | M2 | 未开始 |
| 画幅定义 | `../ai-video/backend/app/video_format.py` | `backend/src/studio/engines/render/` | — | M2 | 未开始 |
| TTS 引擎（火山引擎、音色映射） | `../ai-video/backend/app/engines/tts/` | `backend/src/studio/engines/tts/` | `tests/test_tts_engine.py`、`test_tts_duration.py` | M3 | 已完成 |
| beat 对齐 | `../ai-video/backend/app/services/beat_aligner.py` | `backend/src/studio/engines/tts/` | `tests/test_beat_aligner.py` | M3 | 已完成 |
| 叙事校验 | `../ai-video/backend/app/services/narrative_validator.py` | `stages/narrative/` 中的 `validate_narrative` 工具 | 在 `test_schemas_narrative.py` 等中查找 | M3 | 已完成 |
| 叙事 schema（scene、beat） | `../ai-video/backend/app/schemas/narrative.py`、`beat.py` | `stages/narrative/` 的产物 schema（改为以稳定 id 标识镜头） | `tests/test_schemas_narrative.py` | M3 | 已完成 |
| 兜底文件工具 | `../ai-video/backend/app/services/strategies/openai_agent_runtime.py`（`OpenAICodegenWorkspace`） | `backend/src/studio/agent/fallback_tools.py` | `tests/test_openai_agent_runtime.py` → `backend/tests/agent/test_fallback_tools.py`（运行时部分改写进 `test_openai_runtime.py`） | M1 | 已完成（T10，2026-09-27）：按工作区相对路径读写、范围由 `WriteScope` 决定；保留大小上限与"精确匹配一次"；`validate` 留给 M2 |
| Claude 运行时写法参考 | `../ai-video/backend/app/services/strategies/claude_agent_runtime.py` | `backend/src/studio/agent/`（只参考写法） | `tests/test_claude_agent_runtime.py` | M1 | 未开始 |
| 风格组件内容 | 旧项目 dev DB 的 `prompt_components` 表（注意：dev DB 曾在 git 之外被改动过） | `style_presets` 的初始数据 | — | M5 | 未开始 |
| 风格组件编写经验 | 见下一节 | `stages/animation/prompt.md` | — | M2 | 未开始 |

## 风格组件编写经验（来自旧项目的实践）

风格组件必须包含三条硬约束，否则生成端会放大问题：

1. **布局骨架**：规定画面分区和元素位置。没有骨架时，生成的画面布局会很散乱。
2. **图标克制**：限制图标和装饰元素的使用。否则容易画出火柴人之类的低质量图形。
3. **转场不留中间态**：前一个 beat 的元素要么变换成下一个，要么退场。否则元素会堆积在角落。

另外，旧项目的提示词评审（2026-07-13）结论是：叙事侧的风格组件过于分散，缺少金样本。所以新系统的风格库支持附带范例。
