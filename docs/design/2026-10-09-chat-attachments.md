# 对话框上传附件（图片与文件）

状态：待批准。本文不修改已批准的设计：`UserInput.images` 在[架构设计](2026-09-26-architecture.md)里已经预留（当时"M1 界面只发文本"），本文把它接通，并新增"文件附件"这一输入通道。

## 1. 背景与目标

现在所有 agent 对话框只能发文字。负责人希望能把参考图、截图、风格样例、论文 PDF、资料文本等直接交给 agent。

**目标**：

1. 项目工作台（各阶段）和风格库这两类对话框：可以同时上传**图片**和**文件**。
2. 选题对话（头脑风暴）：**只能上传图片**。它没有工作区，文件无处存放。
3. 图片直接作为多模态输入交给模型；其他文件放进工作区，由 agent 用读工具读取。
4. 历史时间线里的用户消息能看到当时发送的图片缩略图和文件名；刷新页面、"继续"之后不会丢失。

**不做**：

- 先上传、后发送的独立附件接口（方案 B），不显示上传进度条。
- 在后端解析文件内容，比如把 PDF 转成文字、给视频抽帧。文件内容由 agent 自己用工具读。
- 音频、视频文件的特殊处理。它们和其他文件一样只放进 `uploads/`，不做格式校验。音乐导入仍然走现有的 `music_import` 接口。
- 修改历史消息的附件，或在发送后删除附件。

## 2. 已确认的决定

| 项 | 决定 | 来源 |
|---|---|---|
| 支持的附件 | 图片和文件都支持 | 负责人选 C，2026-10-09 |
| 选题对话 | 只支持图片 | 负责人，2026-10-09 |
| 接口形态 | 方案 A：一次 multipart 请求同时提交文字和附件 | 负责人，2026-10-09 |
| 文件位置 | 工作区 `uploads/`；对 agent 只读；纳入快照 | 负责人，2026-10-09 |
| 新依赖 | 不引入。FastAPI 解析 multipart 用到的 `python-multipart` 已经是现有依赖（`music_import` 在用） | 本文 |

## 3. 现状（2026-10-09 排查）

- `agent/runtime.py`：`UserInput(text, images: list[ImageData])` 已经存在。
- `agent/claude_messages.prompt_input`：有图片时改用流式输入，发出 `image` content block。
- `agent/openai_runtime.py`：有图片时发出 `input_image`（data URL）。
- 也就是说，**两个运行时都已经能接收图片**，缺的是 API、持久化和前端这几段。
- `POST /api/sessions/{id}/messages` 的请求体是 `MessageCreate { text }`，端点里构造 `UserInput(text=body.text)`。
- `turns.user_message` 只存文字；"继续"重发一轮从未真正开始的消息时（TD-19），也只重发文字。
- `BlobStore`：内容寻址、跨项目共享。现有的 `GET /api/projects/{id}/blobs/{sha}` 要求项目存在，选题会话用不了。
- `workspace/scope.py`：`guard` 在一轮结束时比较这一轮开始前后的变化，把可写范围之外的改动还原。附件由 API 在这一轮开始**之前**写入，不在比较范围内。
- 三个对话框（`ProjectWorkbenchPage`、`StyleChatPane`、`BrainstormDrawer`）共用 `SessionPanel.vue`。输入框是 ai-elements 的 `PromptInput`，组件库里已经有 `PromptInputActionAddAttachments`，`PromptInputMessage` 也带 `files` 字段。

## 4. 接口

### 4.1 发消息

`POST /api/sessions/{session_id}/messages` 同时接受两种请求体：

- `application/json`：`{ "text": "..." }`。行为不变，旧调用方不用改。
- `multipart/form-data`：一个 `text` 字段，加 0 到多个 `files` 字段。

文字可以为空，但文字和附件不能同时为空。

**校验规则**：任何一条不通过都返回 422，`detail` 用中文写明原因，而且不写入任何东西。

| 规则 | 值 |
|---|---|
| 怎么判断是图片 | 用字节魔数嗅探 png、jpeg、webp、gif，不信任客户端传来的 Content-Type 和扩展名 |
| 单张图片上限 | 5 MB（Anthropic 接口对单张图片的上限） |
| 每轮图片数量上限 | 6 张 |
| 单个文件上限 | 20 MB |
| 每轮文件数量上限 | 10 个 |
| 读取方式 | 分块读，超过上限立即中止（和 `music_import` 的做法一致） |
| 选题会话（会话不属于任何项目） | 出现非图片文件就返回 422："选题对话只支持上传图片" |

上面这些数值写成模块常量，后续可以调整。

### 4.2 读取附件里的图片

新增 `GET /api/sessions/{session_id}/attachments/{sha256}`：只有当这个 sha 出现在这个会话某一轮的 `attachments` 中时才返回字节，否则返回 404。Content-Type 用嗅探结果。

这样选题会话也能回显图片，同时避免把整个 blob 库按 sha 暴露出去。

### 4.3 轮次的返回结构

`TurnOut` 新增 `attachments: list[AttachmentOut]`：

```
AttachmentOut {
  kind: "image" | "file"
  name: str          # 原始文件名，只用于显示
  size: int
  sha256: str | None # 只有 kind=image 时有值
  path: str | None   # kind=file 时有值，是工作区相对路径；
                     # 图片因为模型不支持视觉而被转存成文件时（§5.3），也会有值
}
```

## 5. 后端流程

### 5.1 分流

端点里新增一个纯函数模块 `api/attachments.py`，负责解析、校验和分流，返回 `(UserInput, attachments 记录)`：

- **图片**：字节存进 `BlobStore`，再加进 `UserInput.images`（base64 加嗅探出的 media type）。
- **文件**：写到 `<workdir>/uploads/<turn短id>-<安全文件名>`。
  - 安全文件名：只保留文件名本身；`/`、`\`、控制字符和开头的 `.` 都替换掉；长度截断到 100 个字符。
  - 写入方式：先写临时文件，再原子 rename。
- **追加提示**：如果有文件，就在用户文字末尾追加一段固定格式的说明，供模型阅读：

  ```
  [用户上传的文件]
  - uploads/ab12cd34-paper.pdf（2.3 MB）
  请用读文件工具查看。
  ```

  这段说明只发给模型，`turns.user_message` 仍然只保存用户原文，时间线显示也用原文。

### 5.2 写入时机与并发

- 先确认会话不忙，再写入附件。顺序和现有的 `_refuse_during_upload`、`start_turn` 检查一致：会话忙时返回 409，并且不留下任何文件。
- 如果 `start_turn` 在文件写入之后失败（会话恰好在这段时间内变忙），就删除这次写入的 `uploads/` 文件。blob 不删，它们是内容寻址的，多出来也没有影响。
- turn id 在 `start_turn` 里才生成，所以 `uploads/` 文件名前缀用请求级的随机 8 位短 id，不依赖 turn id。§5.1 里的 `<turn短id>` 指的就是这个短 id。
- `TurnRunner.start_turn` 新增一个可选参数 `attachments`，runner 创建 turn 记录时把它一起写入。

### 5.3 模型不支持图片

当前会话的模型配置 `supports_vision=false` 时：

- 项目和风格会话：把图片也当成文件写进 `uploads/`，走文件通道，并在提示里注明"这是图片，当前模型无法直接查看"。
- 选题会话：返回 422："当前模型不支持图片，请切换模型后再发送"。

### 5.4 `uploads/` 的权限

- 所有阶段的 `WriteScope` 都不包含 `uploads/**`，所以 agent 直接写会被拒绝；用 Shell 写的，一轮结束时会被 `guard` 还原。
- 工作区的只读接口（`list_tree`、`/files`）照常列出 `uploads/`，用户在右侧文件树里能看到上传的文件。
- 快照照常收录 `uploads/`；回滚到某个版本时，`uploads/` 也会回到那个版本的状态。
- 需要确认：各阶段的读取范围（`reads()`，以及 Claude 运行时限制只能读工作区的钩子）是否覆盖 `uploads/`。如果不覆盖，就给所有带工作区的阶段补上 `uploads/**`。

### 5.5 持久化与"继续"

- 迁移 `0011_turn_attachments`：给 `turns` 表新增 `attachments` 列，类型是 JSON，可以为空，旧数据视为 `[]`。
- "继续"重发一轮从未开始的消息时（TD-19），根据 `attachments` 重建 `UserInput`：图片从 blob 取回，文件路径的说明重新拼接。
- 普通的"继续"（`CONTINUE_TEXT`）不重发附件，因为模型会话里已经有了。

## 6. 前端

- `SessionPanel.vue`：
  - 在 `PromptInputFooter` 里加入回形针按钮（`PromptInputActionAddAttachments`），支持粘贴图片和拖拽文件。
  - 待发送的附件以 chip 形式列在输入框上方：图片显示缩略图，文件显示图标、文件名和大小。每个都可以移除。
  - 新增属性 `attachmentAccept?: 'all' | 'images'`，默认 `'all'`。`BrainstormDrawer` 传 `'images'`：只能选图片，粘贴或拖进来的非图片文件会被拦下，并提示"选题对话只支持图片"。
  - 在前端也做和后端相同的大小、数量预校验，及时给出提示。最终仍以后端校验为准。
- `api/endpoints.ts`：发消息时如果带附件，就改用 `FormData`；没有附件时仍然发 JSON。
- 乐观插入的用户消息带上本地附件的预览（`URL.createObjectURL`），服务端确认后改用 `attachments` 渲染，并释放这些本地预览。
- `SessionTimelineItem`：用户消息下面渲染附件。图片缩略图用 `/api/sessions/{id}/attachments/{sha}`，点击可以查看大图；文件显示文件名，点击在右侧文件面板打开这个工作区路径。选题会话没有文件面板，只显示文件名。
- 文字为空但带有附件时，也允许发送。

## 7. 错误处理

| 情况 | 行为 |
|---|---|
| 超过大小或数量限制、类型不对 | 422，中文说明；前端显示在输入框下方，已选的附件保留 |
| 会话正忙或项目正在上传音乐 | 409（和现在一样），不写入任何东西 |
| 写盘失败 | 500；清理这次请求已经写入的 `uploads/` 文件 |
| 模型不支持图片 | 按 §5.3 处理 |
| 附件 sha 不属于这个会话 | 读取接口返回 404 |

## 8. 测试

**后端**：

- `api/attachments.py` 的单元测试：魔数嗅探；各项上限；安全文件名（路径穿越、隐藏文件、超长）；追加提示的格式。
- 端点测试：
  - JSON 请求和原来一致。
  - multipart 请求中，图片进入 `UserInput.images`，文件落到 `uploads/`。
  - 选题会话收到文件时返回 422。
  - 会话忙时返回 409，并且没有写入任何文件。
  - `supports_vision=false` 时，图片被转存成文件。
- 持久化：`TurnOut.attachments` 往返正确；"继续"重发从未开始的一轮时带上附件。
- 写入范围：agent 写 `uploads/` 被拒绝，或在一轮结束时被还原。
- 附件读取接口：sha 属于这个会话时返回 200，否则返回 404。
- 迁移测试：沿用现有的迁移测试方式。

**前端**：

- 选择附件后的 chip 显示，以及移除。
- `'images'` 模式下拦截非图片文件。
- 有附件时用 `FormData` 发送，没有附件时用 JSON。
- 时间线回显图片缩略图和文件名。

**冒烟测试（`make smoke`）**：用本机 Claude 登录账号，在一个项目会话里发一张带文字的图片，确认回答提到了图片内容；再发一个 `.md` 文件，确认 agent 读到了文件内容。

## 9. 涉及的文件（预估）

后端：

- `api/sessions.py`
- `api/schemas.py`
- 新增 `api/attachments.py`
- `agent/runner.py`
- `db/models.py`
- 新增迁移 `0011_turn_attachments.py`
- `db/repo/turns.py`
- 各阶段的 `reads()`（如有需要）

前端：

- `SessionPanel.vue`
- `SessionTimelineItem.vue`
- `optimisticSend.ts`
- `api/endpoints.ts`
- `types/api.ts`
- `BrainstormDrawer.vue`
