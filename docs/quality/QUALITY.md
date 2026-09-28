# 模块质量评级

每个里程碑收尾时更新。评级标准：

| 评级 | 含义 |
|---|---|
| A | 测试覆盖主要路径和边界情况；文档和实现一致；没有已知问题 |
| B | 主要路径有测试；有少量已知缺口，已登记到 tech-debt |
| C | 能用，但测试或文档明显不足 |
| — | 还没有实现 |

| 模块 | 评级 | 已知缺口 | 更新日期 |
|---|---|---|---|
| config / db | A | 12 张表迁移、仓储均有测试；`repo_root()` 已公开，测试不再引用私有常量 | 2026-09-28 |
| workspace（快照库） | A | 快照/回滚/guard/upstream 覆盖主要路径与符号链接、权限边界；快照不再重复读文件，排除目录统一在 workspace 层过滤，guard 还原后清理空目录 | 2026-09-28 |
| jobs | — | M2 | 2026-09-28 |
| agent（运行时、TurnRunner） | B | 三个运行时均有 mock SDK 测试，TurnRunner 覆盖各结束方式；`runner.py`/`openai_runtime.py`/`claude_runtime.py` 已拆分到 400 行以内（原 TD-15/16 及新增拆分）；`ToolContext` 统一构造、步数预算只在 runner 计数（原 TD-17/18）；Claude Bash 沙箱拒读仓库与 data_dir，OpenAI Shell 经 sandbox-exec 沙箱化（原 TD-1/20，残余风险见 TD-27/28）；成本账本取消边界收窄（原 TD-11/12，残余边界见 TD-25/26）；真实 key 冒烟只跑了登录模式（Claude）与本机 sandbox-exec 实测（OpenAI，未过模型） | 2026-09-28 |
| stages.brainstorm | — | M4 | 2026-09-28 |
| stages.topic | C | M1 只有占位定义（提示词 + 可写范围）与结构测试 | 2026-09-28 |
| stages.narrative | C | 同上 | 2026-09-28 |
| stages.animation | C | 同上 | 2026-09-28 |
| engines.render | — | M2 | 2026-09-28 |
| engines.tts | — | M2 | 2026-09-28 |
| search | — | M4 | 2026-09-28 |
| api | B | 各端点 HTTP 层测试、SSE 回放/实时/断线清理、项目级串行、TrustedHost；优雅关闭与 SSE 连接的交互（TD-22）、async 端点里的同步 IO（TD-23） | 2026-09-28 |
| frontend | B | 纯逻辑与 composable 有 vitest（125 个），组件未做挂载测试；浏览器 L4 走查只用 Fake；时间线无上限（TD-24）、工具图片不可预览（TD-21） | 2026-09-28 |
