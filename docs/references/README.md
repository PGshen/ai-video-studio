# references：外部依赖的已验证知识

agent SDK 和前端组件库更新很快，AI 的训练知识可能已经过时。本目录记录**查证过或实测过**的行为，写代码时以这里的内容为准。

## 写法约定

每条事实都要标注状态和来源：

| 标记 | 含义 |
|---|---|
| ✅ 已验证 | 查阅过官方文档或实测过；注明日期和来源 |
| ⚠️ 待验证 | 来自推断或旧代码，还没在新项目中确认；注明计划在哪里验证 |
| ❌ 已否定 | 验证后发现不成立；保留记录，免得以后再次误用 |

发现记录已经过期时，直接更新并改日期，不要追加一条相互矛盾的新记录。

## 索引

| 文件 | 内容 |
|---|---|
| [claude-agent-sdk.md](claude-agent-sdk.md) | Claude Agent SDK（Python） |
| [openai-agents-sdk.md](openai-agents-sdk.md) | OpenAI Agents SDK（Python） |
| [frontend-stack.md](frontend-stack.md) | shadcn-vue、@ai-elements、Tailwind v4 |
| [sse-starlette.md](sse-starlette.md) | sse-starlette、httpx `ASGITransport` 流式测试的限制 |
| [legacy-assets.md](legacy-assets.md) | 旧项目 `../ai-video` 中可迁移的资产 |
| [manim.md](manim.md) | manim（Manim Community）渲染引擎（已下线，ADR 0027，仅供历史参考） |
| [ffmpeg.md](ffmpeg.md) | ffmpeg（本机 Homebrew 安装）：滤镜可用性、字幕叠加方案 |
| [volcengine-tts.md](volcengine-tts.md) | Volcengine TTS：真实合成的时间戳粒度、开头/结尾静音、对齐结果 |
| [tavily.md](tavily.md) | Tavily 搜索与网页抓取：端点、字段、错误码 |
| [html-canvas-agent-spike.md](html-canvas-agent-spike.md) | 真实模型写 Canvas 场景的小试：稳定性、确定性、暴露的问题 |
| [html-video-render.md](html-video-render.md) | HTML 成片：出帧速度、编码色域、混音 `apad` 陷阱、浏览器池 SIGKILL 恢复与内存 |
| [motion-reel-spike.md](motion-reel-spike.md) | 真实模型写短片画面与合成配乐的小试：节拍吸附、谱图自检、暴露的问题与对子项目 3 的影响 |
| [import-music-mv.md](import-music-mv.md) | 导入音乐与音乐 MV（4B）：真实歌曲冒烟读数、成片耗时与大小、上传解析、预览偏移与混音截取 |
| [produce-stage.md](produce-stage.md) | produce 阶段（短片、MV）真实模型冒烟实测：步数、费用、成片耗时、1 MiB 缓冲观察 |
| [librosa.md](librosa.md) | librosa（歌曲节拍分析）：安装与 numba 冷启动耗时、`beat_track` 返回形状与量化、解码路径 |
