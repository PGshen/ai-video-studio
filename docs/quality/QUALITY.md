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
| agent（运行时、TurnRunner） | B | 三个运行时均有 mock SDK 测试，TurnRunner 覆盖各结束方式；`runner.py`/`openai_runtime.py`/`claude_runtime.py` 已拆分到 400 行以内（原 TD-15/16 及新增拆分）；`ToolContext` 统一构造、步数预算只在 runner 计数（原 TD-17/18）；Claude Bash 沙箱拒读仓库与 data_dir，OpenAI Shell 经 sandbox-exec 沙箱化（原 TD-1/20，残余风险见 TD-27/28）；成本账本取消边界收窄（原 TD-11/12，残余边界见 TD-25/26）；真实 key 冒烟只跑了登录模式（Claude）与本机 sandbox-exec 实测（OpenAI，未过模型）；`ToolContext`/`TurnContext` 现在携带 `engine: Engine \| None`，`TurnRunner` 真实装配时透传（原 TD-32），有端到端测试覆盖；M4：无项目会话（`WORKSPACELESS_STAGES`）走无工作区模式（scratch 目录、无快照/`upstream/`/越界检查、`busy_key` 不阻塞项目 turn，`test_runner_brainstorm.py` 覆盖完成/失败/取消/并发/全局上限/校验/重启恢复）；联网模式开关（`_tools_and_web`，`test_web_mode.py`）；`ToolContext` 增加 `session_id` 与 `require_project()`。`native` 模式只验证了 Claude 登录，OpenAI 托管搜索经 OpenRouter 未验证 | 2026-09-29 |
| stages.brainstorm | B | `list_ideas`/`create_idea`/`update_idea`（成功与错误路径：重复标题、非法评分、改已选用/已归档卡片、无数据库连接）有单测；提示词有关键词断言；真实 Claude 登录冒烟通过（无项目会话，`list_ideas` → `web_search` → `create_idea` ×2，卡片在会话运行期间实时出现在界面）。提示词质量靠人工通读：模型写的「反直觉点」偏长（上百字） | 2026-09-29 |
| stages.topic | B | `brief.py` 的检查（缺章节/空章节/事实缺出处或把握程度/全半角与多行写法/低把握与顺序等警告/围栏内 `##`/编号标题）、`check_brief` 工具、`GET /topic/check` 均有单测；真实 Claude 登录冒烟通过（`tools` 与 `native` 两种联网模式各一次，简报 7 章齐全、事实带官方文档出处、`check_brief` 通过）；L4 走查发现的「把握程度：中——说明」写法已放宽。后端 `finalize` 不强制 `check_brief`（计划 D4） | 2026-09-29 |
| stages.narrative | B | `schema`（cue_text 覆盖 narration、id 唯一、transition 枚举）、`validate_narrative`、`synthesize_tts`（假引擎：部分镜头重配、单镜头失败不影响其余、非法叙事不发起合成）均有单测，端到端 turn 测试（`test_narrative_flow.py`）验证叙事产物能喂给动画阶段；提示词有关键词断言。真实 Volcengine 合成已冒烟验证（2026-09-29，短文本无标点）；timing 条目记录配音时的旁白/音色/语速，前端据此判配音是否过期（TD-36，2026-09-29） | 2026-09-29 |
| stages.animation | B | `validate_scenes`/`render_preview`/`suggest_upstream_change` 三个工具都接进 `tools()`（TD-32 修复后）并有完整单测（含 scene_id 定位、超时路径、`suggestions` 表写入）+ 端到端 turn 测试；系统提示词从占位扩到完整版，含三个工具的使用时机和关键词断言 | 2026-09-29 |
| engines.render | A | manim 静态校验、全画质渲染、预览渲染+关键帧抽取均有真实子进程测试（`@pytest.mark.slow`，不是 mock），traceback 定位到镜头号、120 秒超时路径都有覆盖；已知的 manim/ffmpeg 环境行为（音轨 1 秒静音下限、帧边界抽帧误差）记进 `references/manim.md`，代码里已按此设计 | 2026-09-29 |
| engines.tts | B | `VolcengineTTSEngine`（mock HTTP：成功、5xx/429 重试、不可重试错误、mp3 时长解析用真实小 mp3）、`beat_aligner`（正常/插值/缺时长/不匹配）均有测试；真实 API 冒烟通过（`references/volcengine-tts.md`）；带标点文本和长文本下的行为仍待验证 | 2026-09-29 |
| search | B | Tavily 提供方（mock HTTP：成功、`time_range` 映射、`max_results` 夹紧、缺 URL 的结果、空查询、401/432/433/400/422 不重试、429/5xx/超时重试到耗尽、畸形响应、`extract` 截断与失败）有测试；真实 key 冒烟通过（搜索约 2 秒、抓取约 1 秒，见 `references/tavily.md`）；没有多站点抓取质量的系统性验证 | 2026-09-29 |
| worker | B | 领取/心跳/缓存命中/坏镜头报错/reap 均有测试，端到端产出成片的慢测试真实起 manim+ffmpeg；字幕叠加因本机 ffmpeg 缺 drawtext/subtitles 滤镜改用 Pillow 画图+overlay（`references/ffmpeg.md`），换一台带 libass 的机器行为可能不同，未做多环境验证 | 2026-09-29 |
| api | B | 各端点 HTTP 层测试、SSE 回放/实时/断线清理、项目级串行、TrustedHost；M2 新增渲染成片/任务查询/下载/成片定稿四个端点，测试覆盖含代码评审发现并修复的一处问题（重新打开动画阶段清空 `completed_at`，见决策记录 D45）；新增 `GET /projects/{id}/blobs/{sha256}`（TD-21 修复，`api/blobs.py`，Content-Type 从字节嗅探不信任调用方）；新增 `GET /projects/{id}/animation/scene-checks`（TD-33 修复，`api/scene_checks.py::compute_scene_checks` 读时聚合已有的 `turn_events`/`snapshots`，不新增表，10+ 个用例覆盖多会话合并/时间戳覆盖/过期判断）；新增 `GET /projects/{id}/jobs/latest`（TD-34 修复，`api/jobs.py::get_latest_job_endpoint`，薄薄转发已有的 `list_jobs`）；`create_render_job_endpoint` 已有 `queued`/`running` 任务时不再重复排队（TD-35 修复，改返回既有任务、状态码变 200）；优雅关闭与 SSE 连接的交互（TD-22）、async 端点里的同步 IO（TD-23）；M4：`/api/ideas`（增改查、归档/恢复、重复标题 409、评分/标签校验、`picked` 卡片不可归档/改名）、`/api/brainstorm/sessions`、`GET /projects/{id}/topic/check`、`POST /projects` 带 `idea_id`（种入 `topic/notes/idea-card.md`、并发抢卡片输的一方清理项目并 409），以及从选题池到叙事解锁的端到端测试（`test_topic_flow.py`） | 2026-09-29 |
| frontend | B | 纯逻辑与 composable 有 vitest（192 个），组件未做挂载测试（靠 L4 浏览器走查补）；M3 新增叙事画布（镜头卡片/配音播放条/JSON 标签页），L4 走查发现并修复音频不可跳转（文件端点无 Range，TD-37 已改用 `FileResponse` 支持 Range）；配音过期判断（TD-36）走查过；M2 新增动画画布（镜头列表/代码编辑器/成片面板）全部走查过真实渲染/worker/finalize 链路，走查中发现并修复一个真实的响应式竞态 bug（D40）；工具结果图片现在能渲染真缩略图（TD-21 修复，`SessionTimelineItem.vue` 用 `blobUrl`），真实浏览器验证过 blob 端点返回的字节能被 `<img>` 正确识别；镜头列表现在显示"校验通过/失败""预览通过/失败""（已过期）"（TD-33 修复，`useSceneChecksQuery` + `computeSceneStatuses`），真实浏览器验证过两种状态组合都渲染正确；成片面板刷新页面后能恢复上一次渲染的进度/播放器（TD-34 修复，`useLatestJobQuery`），真实浏览器验证过"不点渲染成片、直接打开就能看到已完成的成片"；时间线无上限（TD-24）；M4：新增选题池（卡片网格/编辑/归档/创建项目，`ideaView.ts`）、头脑风暴抽屉（`SessionScope`、无项目会话时按工具结果失效选题池查询）、选题画布（`briefStatus.ts`、`MarkdownFilePane`），vitest 增至 225 个；L4 走查（Fake + 真实 Claude 登录）发现并修复三个问题（保存后检查条不刷新、网格列数按视口、`把握程度` 写法），会话面板搬到 `components/session/` 后 M1 的既有测试未改断言 | 2026-09-29 |
