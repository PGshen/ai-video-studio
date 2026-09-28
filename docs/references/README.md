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
| [manim.md](manim.md) | manim（Manim Community）渲染引擎 |
