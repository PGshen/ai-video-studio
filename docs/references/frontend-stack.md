# 前端技术栈：Vue 3 + Tailwind v4 + shadcn-vue

## 事实

| 状态 | 内容 | 来源 |
|---|---|---|
| ⚠️ 待验证 | shadcn-vue 的 registry 已包含 `@ai-elements`，提供 AI 原生的 conversation、message 等组件 | 负责人提供（2026-09-26）；M1 初始化时确认组件清单并补充到这里 |
| ⚠️ 待验证 | 工作台外壳可以用 `npx shadcn-vue@latest add dashboard-01` 初始化 | 负责人提供（2026-09-26）；M1 验证 |
| ⚠️ 待验证 | Tailwind v4 不需要 `tailwind.config.js`，在 CSS 中通过 `@import "tailwindcss"` 配置 | 旧项目经验（React 版）；M1 验证 |
| ⚠️ 待验证 | 浏览器原生的 `EventSource` 不能设置请求头，而且不能控制重连时的 `after_seq`，所以用基于 fetch 的 SSE 客户端 | 通用知识；M1 选定具体的库后在这里记录 |
