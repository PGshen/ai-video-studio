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
| config / db | A | 12 张表迁移、仓储均有测试；`test_config` 引用私有常量（TD-3） | 2026-09-28 |
| workspace（快照库） | B | 快照/回滚/guard/upstream 覆盖主要路径与符号链接、权限边界；快照重复读文件（TD-4）、排除目录过滤与空目录（TD-5） | 2026-09-28 |
| jobs | — | M2 | 2026-09-28 |
| agent（运行时、TurnRunner） | B | 三个运行时均有 mock SDK 测试，TurnRunner 覆盖各结束方式；runner/openai_runtime 过大（TD-15/16）、成本账本与取消边界（TD-11/12）、OpenAI Shell 无沙箱（TD-20）、Claude 联网外发剩余风险（TD-1）；真实 key 冒烟只跑了登录模式 | 2026-09-28 |
| stages.brainstorm | — | M4 | 2026-09-28 |
| stages.topic | C | M1 只有占位定义（提示词 + 可写范围）与结构测试 | 2026-09-28 |
| stages.narrative | C | 同上 | 2026-09-28 |
| stages.animation | C | 同上 | 2026-09-28 |
| engines.render | — | M2 | 2026-09-28 |
| engines.tts | — | M2 | 2026-09-28 |
| search | — | M4 | 2026-09-28 |
| api | B | 各端点 HTTP 层测试、SSE 回放/实时/断线清理、项目级串行、TrustedHost；优雅关闭与 SSE 连接的交互（TD-22）、async 端点里的同步 IO（TD-23） | 2026-09-28 |
| frontend | B | 纯逻辑与 composable 有 vitest（125 个），组件未做挂载测试；浏览器 L4 走查只用 Fake；时间线无上限（TD-24）、工具图片不可预览（TD-21） | 2026-09-28 |
