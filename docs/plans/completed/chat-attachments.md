# chat-attachments：对话框上传附件（图片与文件）

<!-- 本计划实现 docs/design/2026-10-09-chat-attachments.md（含 §10 修订）。只写结构和意图，不写实现代码。 -->

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成 |
| 里程碑 | 功能增强（不在架构设计 §10 的编号里程碑中） |
| 设计依据 | [chat-attachments 设计](../../design/2026-10-09-chat-attachments.md)（负责人 2026-10-09 批准，含 §10 修订 R1、R2） |
| 分支 | `chat-attachments`，从 main 切出 |
| 批准记录 | 2026-10-09：负责人批准计划；2026-10-09：负责人验收通过 |
| 执行方式 | 会话内直接执行，完成后一个独立评审检查整个分支 |

## 目标

在项目工作台和风格库的对话框里，可以随消息上传图片和文件；选题对话只能上传图片。图片作为多模态输入直接交给模型；文件放进工作区的 `uploads/` 目录，由 agent 自己读取。历史时间线里能看到发送过的附件，刷新页面或"继续"之后也不会丢失。

## 范围

**包含：**

- 附件的解析、校验和分流：新增模块 `api/attachments.py`。
- 发消息接口同时接受 multipart 请求。
- 新增附件图片读取接口。
- `turns.attachments` 列，以及迁移 `0011`。
- runner 透传附件；"继续"一轮从未开始的消息时，带上原来的附件重发。
- `uploads/` 对 agent 只读。
- 风格草稿的清理和保存都跳过 `uploads/`（修订 R1）。
- 文件说明里标注能否直接读取（修订 R2）。
- 前端：附件按钮、粘贴、拖拽、附件 chip 和警告、`FormData` 发送、时间线回显。选题对话只允许图片。
- 登记技术债："大于 300 kB 的 PDF 读不了"。
- 冒烟测试。

**不包含：** 先上传、后发送的独立附件接口；上传进度条；后端解析文件内容（PDF 转文本等）；音视频的特殊处理；修改或删除已发送的附件。

## 全局约束

- 限制（设计 §4.1）：
  - 图片按魔数判断类型，只接受 png、jpeg、webp、gif。单张不超过 **5 MB**，每轮最多 **6** 张。
  - 文件单个不超过 **20 MB**，每轮最多 **10** 个。
  - 这些限制写成 `api/attachments.py` 的模块常量；前端用同样的数值做预校验。
- 选题会话（`stage.workspaceless`）出现非图片附件时，返回 422："选题对话只支持上传图片"。
- `turns.user_message` 只保存用户原文。追加给模型的文件说明只放进 `UserInput.text`，不写进数据库。
- 文件名格式是 `uploads/<请求级 8 位十六进制短 id>-<安全文件名>`。安全文件名只保留文件名本身；`/`、`\`、控制字符和开头的 `.` 替换成 `_`；长度截断到 100 个字符。
- 读取上限复用现有常量 `claude_scope.MAX_READ_IMAGE_BYTES`（300 kB）和 `fallback_tools.MAX_READ_BYTES`（2 MB），不另写一份数值。
- 不引入新依赖。`python-multipart` 已经通过传递依赖装好，`music_import` 已经在用：本计划不把它写成显式依赖，但要在「决策记录」里写一行说明。
- 校验失败、会话忙（409）或项目正在上传音乐（409）时，**不能留下任何 `uploads/` 文件**。

## 评审重点

以下是任务测试不容易覆盖、但最可能影响使用的情况。每一条在负责实现它的任务里都要有对应的测试。

1. 文件名里带 `../`、绝对路径、隐藏文件名、中文或超长名字：必须落在 `uploads/` 下，并且中文能正常保留（T1）。
2. 写完文件之后会话变忙（`start_turn` 抛出 `SessionBusyError`）：要删掉这次写入的文件，并返回 409（T3）。
3. 一次请求里有同一张图片的两份，或者文件名相同的两个文件：图片在 blob 库里去重，但两份都要记进 `attachments`；同名文件因为带短 id，不会互相覆盖（T1/T3）。
4. agent 在一轮里用 Shell 改写或删除 `uploads/` 下的文件：一轮结束时要被还原（T4）。
5. 风格草稿里有 `uploads/` 时，保存成正式版本要成功，正式版本里不能出现 `uploads/`，草稿被删后附件文件也一起消失（T4）。

## 验收标准

- [x] AC1：项目会话发送"文字 + 1 张图片 + 1 个 `.md` 文件"后，模型的回答提到了图片内容，也读到了 `.md` 的内容；`uploads/` 下出现这个文件，右侧文件树能看到它。（验证方式：`make smoke` 新增的用例，加上浏览器截图）
- [x] AC2：选题对话只能选图片；如果绕过前端直接发文件，接口返回 422。（验证方式：端点测试，加上浏览器操作截图）
- [x] AC3：刷新页面后，时间线里的用户消息仍然显示图片缩略图和文件名。（验证方式：浏览器截图）
- [x] AC4：超出大小或数量限制、类型不对时返回 422，前端显示中文提示，已选的附件保留。（验证方式：端点测试和组件测试）
- [x] AC5：agent 改不了 `uploads/`；回滚到某个快照时，`uploads/` 回到那个版本的状态。（验证方式：runner 测试）
- [x] AC6：风格对话可以上传文件；保存风格成功，正式版本里不含 `uploads/`。（验证方式：style store 测试和 runner_style 测试）
- [x] AC7：大于 300 kB 的 PDF 在附件 chip 上显示警告；发给模型的说明里标明"可能无法直接读取"。（验证方式：单元测试和组件测试）
- [x] AC8：`make check` 全绿。

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：附件解析与分流模块（完成）

- **目标**：用一个纯函数模块把上传内容变成 `UserInput` 加附件记录。这个模块不依赖 FastAPI 的请求对象。
- **涉及文件**：新增 `backend/src/studio/api/attachments.py`；新增 `backend/tests/api/test_attachments.py`。
- **接口与要点**：
  - 输入 `IncomingFile(name: str, data: bytes)`。分块读取、超限立即中止这一步放在端点里做（T3），T1 只拿到已经读好的 `bytes`。
  - `sniff_image(data) -> str | None`：返回 media type，不是图片时返回 `None`。
  - `safe_name(name) -> str`。
  - `AttachmentRecord`：一个 dataclass，字段是 `kind`（`"image"` 或 `"file"`）、`name`、`size`、`sha256: str | None`、`path: str | None`。它要能直接序列化成 `turns.attachments` 的 JSON。
  - `PreparedInput`：字段是 `user_input: UserInput`、`records: list[AttachmentRecord]`、`written: list[Path]`。其中 `written` 记录这次写入的文件，失败时用来清理。
  - 主函数：
    ```
    prepare_input(
        text, files, *,
        workdir: Path | None, blobs: BlobStore,
        runtime: str, supports_vision: bool,
    ) -> PreparedInput
    ```
    - `workdir is None` 表示选题会话：有文件就报错；`supports_vision=False` 也报错。
    - 当 `supports_vision=False` 且有工作区时，图片转成文件。
    - 返回 `AttachmentError(message)` 时，端点把它转成 422。
  - `file_note(records, runtime) -> str`：生成追加给模型的说明段，格式见设计 §5.1。每一行带大小和可读性标注，规则见修订 R2。按 runtime 区分提示："claude" 提示用 Bash 提取；"openai" 提示如实告诉用户。
  - 校验必须在**写任何东西之前**全部完成。写入失败时，删掉已经写入的文件再抛出异常。
- **测试**：
  - 魔数：4 种图片格式各一个，再加一个伪装成 `.png` 的文本文件。
  - 各项上限，边界值要测"刚好等于上限"和"超过 1 字节"。
  - `safe_name`：覆盖评审重点 1 的所有情况。
  - 选题会话收到文件 → 报错；选题会话 + 模型不支持图片 → 报错。
  - 模型不支持图片时，图片落进 `uploads/`。
  - 同一张图片两份，`records` 里有两条（评审重点 3）。
  - `file_note`：两种 runtime 各测一次；300 kB 的 PDF、2 MB 的文本、二进制文件在 openai 下各测一次。
  - 文字为空，而且没有附件 → 报错。
- **完成标准**：上面的测试全部通过；这个模块不 import fastapi。
- **验证命令**：`cd backend && uv run pytest tests/api/test_attachments.py -q`，然后 `make check`。

### T2：持久化——`turns.attachments`（完成）

- **目标**：轮次记录能保存附件，接口能返回附件。
- **涉及文件**：
  - `backend/src/studio/db/models.py`（`Turn.attachments`，类型 JSON，可以为空）
  - 新增 `backend/src/studio/db/migrations/versions/0011_turn_attachments.py`
  - `backend/src/studio/db/repo/turns.py`：`TurnValue.attachments: list[dict]`，空值读成 `[]`；`create_turn_if_session_idle(..., attachments: list[dict] | None = None)`
  - `backend/src/studio/api/schemas.py`：`AttachmentOut`；`TurnOut.attachments`
  - `backend/src/studio/api/sessions.py`：`_turn_out`
  - `frontend/src/types/api.ts`：`AttachmentOut`；`Turn.attachments`
- **测试**：
  - `tests/db/test_migrate.py`：迁移以后新列存在，旧行读出来是 `[]`。
  - `tests/db/test_repo_turns.py`：写入后读回一致。
  - `tests/api/test_sessions.py`：`GET /sessions/{id}` 返回 `attachments`。
- **完成标准**：旧数据库升级后，现有测试全部通过。
- **验证命令**：`make check`。

### T3：发消息接口与附件读取接口（完成）

- **目标**：用 multipart 发消息能跑通；可以读取附件里的图片。
- **涉及文件**：
  - `backend/src/studio/api/sessions.py`
  - `backend/src/studio/agent/runner.py`：`start_turn(session_id, user_input, *, attachments: list[dict] | None = None)`，透传给 repo
  - `backend/src/studio/api/deps.py`（如果需要拿到 blobs 或 settings）
  - `backend/tests/api/test_sessions.py`、`backend/tests/api/test_brainstorm_sessions.py`、`backend/tests/agent/test_runner.py`
- **接口与要点**：
  - 端点按 `Content-Type` 分支：JSON 走原来的逻辑。multipart 时：
    1. 先检查 `_refuse_during_upload`，再检查会话是否正忙（latest turn 状态，复用现有判断），这一步不写任何东西。
    2. 分块读取每个 `files`，超限立即返回 422。
    3. 确定 workdir：
       - 项目会话：`project_dir(data_dir, project_id)`。
       - 风格会话：`style_store.open_draft` 之后用 `draft_dir`（风格已删除时返回 404）。
       - 选题会话：`None`。
    4. 调用 `prepare_input`。
    5. 调用 `start_turn`。如果抛出 `SessionBusyError`，删掉 `written` 里的文件，再返回 409。
  - 新增 `GET /api/sessions/{session_id}/attachments/{sha256}`：sha 必须出现在这个会话某一轮的 `attachments[*].sha256` 里，否则返回 404。Content-Type 复用 `api/blobs.py` 的嗅探函数；如果它是私有函数，就挪到 `api/attachments.py` 共用。
  - "继续"（TD-19，从未开始过的一轮）：根据 `turn.attachments` 重建 `UserInput`：
    - 图片：从 blob 取出，转成 `ImageData`。
    - 文件：用 `file_note` 重新拼接说明。
    - 重发时把原来的 `attachments` 传回给 `start_turn`。
- **测试**：
  - multipart 发图片：fake runtime 收到 `images`。
  - 发文件：`uploads/` 有文件，`user_message` 是原文。
  - 选题会话发文件 → 422；选题会话发图片 → 202。
  - 会话忙 → 409，并且 `uploads/` 为空（评审重点 2，要模拟两种情况：start_turn 之前就忙，以及 start_turn 抛出 busy）。
  - 超限 → 422，并且没有写入任何东西。
  - 附件读取接口：sha 属于这个会话时返回 200，属于别的会话时返回 404。
  - "继续"一轮从未开始的消息时，图片随消息重发。
- **完成标准**：AC2 和 AC4 的后端部分有测试证据。
- **验证命令**：`make check`。

### T4：`uploads/` 只读，以及风格草稿的处理（完成）

- **目标**：agent 改不了 `uploads/`；风格草稿的清理和保存都跳过 `uploads/`（修订 R1）。
- **涉及文件**：
  - `backend/src/studio/workspace/scope.py`：新增 `UPLOADS_DIR = "uploads"`。在 `is_writable` 里对 `uploads/` 一律返回 False，这样不用逐个修改各阶段的 `WriteScope`，`guard` 和 Claude/apply_patch 的事前检查也都会自动生效。
  - `backend/src/studio/styles/store.py`：`prune_draft`、`_read_tree`（或者它在保存时的调用方）、`_install` 都跳过 `uploads/`。
  - 测试：`backend/tests/workspace/`、`backend/tests/agent/test_runner.py`、`backend/tests/agent/test_runner_style.py`、`backend/tests/styles/`
- **测试**：
  - `is_writable(scope_with_star, "uploads/x")` 返回 False。
  - runner：agent 用 Shell 改写或删除 `uploads/` 下的文件后，一轮结束时被还原（评审重点 4）。
  - 回滚快照时，`uploads/` 回到那个版本的状态（AC5）。
  - 风格：`prune_draft` 保留 `uploads/`；草稿里有 `uploads/` 时保存成功，正式版本里没有 `uploads/`，草稿被删除（评审重点 5、AC6）。
- **完成标准**：上面的测试全部通过；现有的写入范围测试没有退化。
- **验证命令**：`make check`。

### T5：前端——发送附件（完成）

- **目标**：对话框可以添加附件、预览附件、把附件发出去。
- **涉及文件**：
  - `frontend/src/components/session/SessionPanel.vue`
  - 新增 `frontend/src/components/session/attachmentRules.ts`：前端限制常量、`classify(file, accept) -> {ok, warning?, error?}`，可读性警告规则和修订 R2 一致
  - `frontend/src/api/endpoints.ts`：`sendMessage` 有附件时用 `uploadForm` 发 `FormData`，否则发 JSON
  - `frontend/src/components/session/optimisticSend.ts`（乐观消息带本地预览）
  - `frontend/src/features/ideas/BrainstormDrawer.vue`：传入 `attachmentAccept="images"`
  - 测试：`attachmentRules.spec.ts`、`SessionPanel.spec.ts`、`endpoints.spec.ts`
- **接口与要点**：
  - `SessionPanel` 新增属性 `attachmentAccept?: 'all' | 'images'`。
  - 先确认 ai-elements 的 `PromptInput` 在 `submit` 时给出的 `files`（`FileUIPart`，可能是 blob URL）能不能拿回原始 `File`。拿不回的话，在 `SessionPanel` 里通过 `addFiles` 或 context 自己保存原始 `File`。确认结果写进「意外与发现」。
  - 回形针按钮用 `PromptInputActionAddAttachments`；粘贴和拖拽用组件库自带的能力。
  - chip 显示缩略图或文件图标、文件名、大小、警告，可以移除。
  - 发送失败时附件保留；发送成功后清空附件，并释放 object URL。
  - 文字为空但有附件时，允许发送。
- **测试**：
  - `classify`：各项上限，以及 images 模式拦下 `.pdf`，300 kB 的 PDF 带警告。
  - `sendMessage`：有附件时请求体是 FormData，没有附件时是 JSON。
  - `SessionPanel`：选择附件后 chip 出现；422 时附件保留，并显示错误信息。
- **完成标准**：AC2 和 AC4 的前端部分、AC7 的前端部分都有测试。
- **验证命令**：`make check`。

### T6：前端——时间线回显（完成）

- **目标**：历史消息里显示附件。
- **涉及文件**：
  - `frontend/src/components/session/SessionTimelineItem.vue`，以及用户消息的数据来源（`groupTimeline.ts` 或 `useSessionStream.ts`，以实际代码为准）：把 `turn.attachments` 带进用户消息
  - 新增 `frontend/src/api/endpoints.ts::attachmentUrl(sessionId, sha)`
  - 测试：`SessionTimelineItem.spec.ts`
- **接口与要点**：
  - 图片显示缩略图，点击后查看大图（如果有现成的 Dialog，就复用）。
  - 文件显示名字：项目会话点击后在右侧文件面板打开对应路径，复用工作台现有的打开文件事件；风格和选题会话只显示文件名。
  - 文件已经不存在时（修订 R1）显示提示，不报错。
- **测试**：图片缩略图的 src 正确；文件 chip 被点击时发出打开文件的事件；没有附件的旧消息渲染不变。
- **完成标准**：AC3 有组件测试，在浏览器里能看到。
- **验证命令**：`make check`。

### T7：冒烟测试、技术债与自验证（完成）

- **目标**：用真实模型验证整条链路，补齐记录。
- **涉及文件**：
  - `backend/tests/smoke/` 下新增一个用例，用 claude-login：一张小 png 加一个 `.md`，断言回答提到了图片里的内容和 md 里的一句暗号
  - `docs/quality/tech-debt.md`：登记"大于 300 kB 的 PDF 读不了（修订 R2）"
  - 本计划的「验证记录」
- **测试**：`make smoke`（只跑新增的用例即可）；`make dev` 启动后在浏览器里走一遍 AC1、AC2、AC3、AC6，并截图。
- **完成标准**：AC1 到 AC8 都有证据。
- **验证命令**：`make check`、`make smoke`。

## 进度

- 2026-10-09 — T1 — `api/attachments.py` 与 37 个单元测试完成，make check 绿
- 2026-10-09 — T2 — 迁移 0011、`TurnValue/TurnOut.attachments`、前端 `AttachmentOut` 类型，make check 绿

## 下一步

- 无（已完成）。评审遗留的 Minor 见「意外与发现」，负责人尚未决定是否排期。

## 决策记录

- 2026-10-09 — 收尾：`uploads/` 只读、项目忙时拒绝写工作区的附件写成 [ADR 0026](../../decisions/0026-对话附件放在工作区uploads目录且对agent只读.md)。
- 2026-10-09 — 写入保护放在 `is_writable` 统一处理 `uploads/`，不逐个修改各阶段的 `WriteScope` — 这样所有阶段一次生效，以后新增的阶段也不会漏掉。
- 2026-10-09 — T1：`AttachmentRecord` 多一个 `binary` 字段（内容不是 UTF-8 文本），另加 `compose_text`（原文 + 文件说明）和 `discard(written)` — `file_note` 判断 OpenAI 下能否读取、"继续"重建说明都需要它，只能在上传时算出并持久化。
- 2026-10-09 — T1：模型不支持图片时转存的图片记录为 `kind="image"`，同时有 `sha256`（缩略图）和 `path`（文件说明）— 与设计 §4.3 的 `path` 说明一致。
- 2026-10-09 — T2：前端 `TurnOut.attachments` 定为可选（`attachments?:`），消费方用 `?? []` — 后端总会返回，但前端大量 spec 夹具手写 `TurnOut`；可选可以避免无关改动。
- 2026-10-09 — T3：`TurnRunner.start_turn` 多一个 `user_message` 关键字参数 — `UserInput.text` 已经拼上文件说明，`turns.user_message` 要存原文（全局约束）。
- 2026-10-09 — T3：会话的工作目录判断与 `TurnRunner._execute` 一致：有项目 → 项目工作区；无项目有 `subject_id` → 风格草稿；都没有 → 选题会话。风格阶段本身被标为 `workspaceless`，不能用阶段标记判断。
- 2026-10-09 — T3：JSON 分支改为手动解析 `MessageCreate`，失败时 422 的 detail 是中文字符串（以前是 FastAPI 的校验列表）— 同一端点要同时接受 JSON 和 multipart。
- 2026-10-09 — T4：同一项目里另一个会话的一轮正在运行时，带文件（会写工作区）的消息返回 409；只带图片的照常排队 — 正在运行的那一轮结束时，越界检查会把新出现的 `uploads/` 文件当越权改动删掉。设计 §5.2 只要求检查本会话是否忙，这里补上项目级检查。
- 2026-10-09 — T4：styles 不能依赖 workspace（结构规则 4），所以 `styles/layout.py` 另写一份 `UPLOADS_DIR`，用 `tests/styles/test_layout.py` 保证和 `workspace/scope.py` 一致。
- 2026-10-09 — T5：回形针用 `PromptInputButton` 加 `openFileDialog` 自己写（`AttachButton.vue`）— 组件库的 `PromptInputActionAddAttachments` 是下拉菜单项，不能单独放。
- 2026-10-09 — T5：带附件的发送失败时，`onSubmit` 向 `PromptInput` 重新抛出错误，让它保留附件、恢复文字；不带附件时照旧吞掉错误，行为不变。409 改为优先显示后端给的中文 detail（项目忙时的提示和会话忙不同）。
- 2026-10-09 — T5：乐观消息的本地预览挪到 T6 和时间线渲染一起做 — 渲染组件在 T6。
- 2026-10-09 — T6：文件附件在项目会话里改成新标签页打开工作区原文件（`workspaceFileUrl`），不在右侧文件面板打开 — 各阶段画布各自管理文件选中状态，没有统一的“打开文件”入口，接入要改每个画布，超出本计划。风格和选题会话只显示文件名，所以修订 R1 的“文件已不存在”提示不会出现。
- 2026-10-09 — `python-multipart` 不写成显式依赖 — 它已经通过传递依赖装好，`music_import` 已经在用；遵守"不引入计划外依赖"这条约束。

## 意外与发现

- 2026-10-09 — 独立评审遗留的 Minor（未修，待负责人决定）：M3 重发从未开始的一轮时不检查当前模型是否支持图片；M4 大小上限在 Starlette 收完整个请求体后才生效（不是流式中止，也没有总大小上限）；M5 项目会话回滚后文件链接会打开 404；M6 选题对话里混合粘贴图片和 PDF 时 PDF 被静默丢掉，HEIC/BMP 的提示文案容易误解；M7 前端“可能读不全”警告不考虑 OpenAI 二进制和不支持图片的模型；M8 消息接口的请求体从 OpenAPI 文档消失；M9 风格已删除、不支持图片这两种情况缺端点层测试；M10 `safe_name` 不处理 Windows 非法字符（`: * ? " < > |`、末尾的 `.`），执行 windows-native 计划时需要处理。
- 2026-10-09 — T7：一次 `make check` 里 `router.spec.ts` 的“resolves /projects/:id/:stage”超时（5 s，动态加载页面组件）；当时机器同时开着 dev server 和浏览器。单独重跑 3 次、完整 `make check` 重跑都通过，判断是负载下的偶发超时，不是本计划引入的。
- 2026-10-09 — T7：第一版冒烟提示（“原样告诉我暗号”）被模型当成提示注入而拒绝；改成真实的选题场景（参考图配色 + 资料里的项目代号）后通过。
- 2026-10-09 — T7：浏览器走查用的是负责人自己开着的 `make dev`（热重载已经加载本分支代码），启动时迁移把 `data/studio.db` 升到了 0011（只新增一个可为空的列）。走查建了一个临时项目「附件功能验证（可删除）」。
- 2026-10-09 — T5：`PromptInput` 提交时 `files` 是 `{...AttachmentFile, url: dataUrl}`，原始 `File` 仍在 `.file` 上，可以直接拿来上传；代价是组件库会先把每个附件读成 data URL（20 MB 的文件也会读一遍），本地单人使用可以接受。jsdom 下 `URL.createObjectURL` 不认 jsdom 的 File，测试里需要打桩。
- 2026-10-09 — T4：runner 的 guard 测试（Shell 改 `uploads/` 被还原）在改动前就能通过，因为 topic 阶段的写入范围本来就不含 `uploads/`；`is_writable` 的改动保护的是写入范围更宽的阶段，由 `test_scope.py::test_uploads_are_never_writable` 覆盖。
- 2026-10-09 — 前端 `pnpm run typecheck`（`vue-tsc --noEmit`）对 `files: []` 的 solution tsconfig 实际上什么都不检查；用 `-p tsconfig.app.json` 实测有 52 处既有错误（多在 spec 里）。不属于本计划，已经开了单独的任务；本计划的改动用 `-p tsconfig.app.json` 确认不新增错误。
- 2026-10-09 — 写计划时发现风格对话的 cwd 是草稿目录，以及读工具有大小上限。已经升级给负责人，结论写进设计修订 R1、R2。

## 阻塞

- 无

## 验证记录

- AC1：`make smoke SMOKE_ARGS="-k attachments_claude_login"` → 1 passed（证据 `data/evidence/chat-attachments/smoke/20261009T072412Z-attachments-claude-login.json`：模型用 Read 读了 `uploads/…-资料.md`，回答“左边纯蓝、右边纯黄”和代号“青柠-4271”）。浏览器里在临时项目的选题会话中发送 png + md，回答同样正确；`GET /api/projects/{id}/files/uploads/85577dab-资料.md` 返回 200。
- AC2：浏览器打开选题页的头脑风暴面板，文件框 `accept="image/png,image/jpeg,image/webp,image/gif"`，选择 PDF 后没有 chip，输入框上方显示“选题对话只支持图片”；接口层见 `test_message_attachments.py::TestBrainstormSession`。
- AC3：发送后刷新页面，用户消息下的缩略图地址是 `/api/sessions/{id}/attachments/{sha}`，图片加载成功（naturalWidth 64），文件链接到工作区原文件；组件测试见 `SessionTimelineItem.spec.ts`。
- AC4：`test_attachments.py` 的上限用例、`test_message_attachments.py::test_oversized_file_is_422_and_writes_nothing`、`SessionPanel.spec.ts` 的“超过上限的附件不发送”“发送失败时附件保留”。
- AC5：`test_scope.py::test_uploads_are_never_writable`、`test_runner.py::TestGuard::test_shell_changes_to_uploads_are_restored`、`test_snapshot.py::test_scan_includes_uploads`。
- AC6：`test_message_attachments.py::TestStyleSession`、`tests/styles/test_store.py::test_uploads_are_kept`、`test_save_leaves_uploads_behind`。没有在负责人的风格库里实际走查（会产生风格草稿）。
- AC7：浏览器里 400 kB 的 PDF chip 显示“agent 可能读不到全文，建议转成文本后再上传”；`test_attachments.py::TestFileNote`。
- AC8：`make check` 全部通过。
