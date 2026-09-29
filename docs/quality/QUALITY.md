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
| jobs | B | `create_job`/`claim_next`/心跳/进度/完成/失败/`reap_stale_running` 均有测试；`claim_next` 只保证同进程内不重复领取，跨进程强一致性明确不做（设计选择，见 D2），未做多进程并发验证 | 2026-09-29 |
| agent（运行时、TurnRunner） | B | 三个运行时均有 mock SDK 测试，TurnRunner 覆盖各结束方式；`runner.py`/`openai_runtime.py`/`claude_runtime.py` 已拆分到 400 行以内（原 TD-15/16 及新增拆分）；`ToolContext` 统一构造、步数预算只在 runner 计数（原 TD-17/18）；Claude Bash 沙箱拒读仓库与 data_dir，OpenAI Shell 经 sandbox-exec 沙箱化（原 TD-1/20，残余风险见 TD-27/28）；成本账本取消边界收窄（原 TD-11/12，残余边界见 TD-25/26）；真实 key 冒烟只跑了登录模式（Claude）与本机 sandbox-exec 实测（OpenAI，未过模型）；`ToolContext`/`TurnContext` 现在携带 `engine: Engine \| None`，`TurnRunner` 真实装配时透传（原 TD-32），有端到端测试覆盖 | 2026-09-29 |
| stages.brainstorm | — | M4 | 2026-09-28 |
| stages.topic | C | M1 只有占位定义（提示词 + 可写范围）与结构测试 | 2026-09-28 |
| stages.narrative | C | 同上 | 2026-09-28 |
| stages.animation | B | `validate_scenes`/`render_preview`/`suggest_upstream_change` 三个工具都接进 `tools()`（TD-32 修复后）并有完整单测（含 scene_id 定位、超时路径、`suggestions` 表写入）+ 端到端 turn 测试；系统提示词从占位扩到完整版，含三个工具的使用时机和关键词断言 | 2026-09-29 |
| engines.render | A | manim 静态校验、全画质渲染、预览渲染+关键帧抽取均有真实子进程测试（`@pytest.mark.slow`，不是 mock），traceback 定位到镜头号、120 秒超时路径都有覆盖；已知的 manim/ffmpeg 环境行为（音轨 1 秒静音下限、帧边界抽帧误差）记进 `references/manim.md`，代码里已按此设计 | 2026-09-29 |
| engines.tts | — | M3 | 2026-09-29 |
| search | — | M4 | 2026-09-28 |
| worker | B | 领取/心跳/缓存命中/坏镜头报错/reap 均有测试，端到端产出成片的慢测试真实起 manim+ffmpeg；字幕叠加因本机 ffmpeg 缺 drawtext/subtitles 滤镜改用 Pillow 画图+overlay（`references/ffmpeg.md`），换一台带 libass 的机器行为可能不同，未做多环境验证 | 2026-09-29 |
| api | B | 各端点 HTTP 层测试、SSE 回放/实时/断线清理、项目级串行、TrustedHost；M2 新增渲染成片/任务查询/下载/成片定稿四个端点，测试覆盖含代码评审发现并修复的一处问题（重新打开动画阶段清空 `completed_at`，见决策记录 D45）；新增 `GET /projects/{id}/blobs/{sha256}`（TD-21 修复，`api/blobs.py`，Content-Type 从字节嗅探不信任调用方）；新增 `GET /projects/{id}/animation/scene-checks`（TD-33 修复，`api/scene_checks.py::compute_scene_checks` 读时聚合已有的 `turn_events`/`snapshots`，不新增表，10+ 个用例覆盖多会话合并/时间戳覆盖/过期判断）；新增 `GET /projects/{id}/jobs/latest`（TD-34 修复，`api/jobs.py::get_latest_job_endpoint`，薄薄转发已有的 `list_jobs`）；`create_render_job_endpoint` 已有 `queued`/`running` 任务时不再重复排队（TD-35 修复，改返回既有任务、状态码变 200）；优雅关闭与 SSE 连接的交互（TD-22）、async 端点里的同步 IO（TD-23） | 2026-09-29 |
| frontend | B | 纯逻辑与 composable 有 vitest（166 个），组件未做挂载测试（靠 L4 浏览器走查补）；M2 新增动画画布（镜头列表/代码编辑器/成片面板）全部走查过真实渲染/worker/finalize 链路，走查中发现并修复一个真实的响应式竞态 bug（D40）；工具结果图片现在能渲染真缩略图（TD-21 修复，`SessionTimelineItem.vue` 用 `blobUrl`），真实浏览器验证过 blob 端点返回的字节能被 `<img>` 正确识别；镜头列表现在显示"校验通过/失败""预览通过/失败""（已过期）"（TD-33 修复，`useSceneChecksQuery` + `computeSceneStatuses`），真实浏览器验证过两种状态组合都渲染正确；成片面板刷新页面后能恢复上一次渲染的进度/播放器（TD-34 修复，`useLatestJobQuery`），真实浏览器验证过"不点渲染成片、直接打开就能看到已完成的成片"；时间线无上限（TD-24） | 2026-09-29 |
