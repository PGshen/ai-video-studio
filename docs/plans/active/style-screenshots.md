# style-screenshots：风格库截图与封面

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 风格库增强（M5 之后） |
| 设计依据 | ADR [0019](../../decisions/0019-风格库改用磁盘目录存储.md)（目录存储与草稿流程）；本计划 T1 新增 ADR 0022（风格目录允许二进制截图）；设计在 2026-10-08 的对话中确定，要点见下方「设计要点」 |
| 分支 | `style-screenshots`（独立 worktree） |
| 批准记录 | 2026-10-08：负责人批准设计（截图走草稿流程、不复制进项目）；2026-10-08：负责人批准计划，选择 native 方式（本会话内联执行，结束后整分支评审一次） |

## 目标

每套风格可以保存若干张截图，第一张作为封面显示在风格库卡片上，用户浏览风格库时一眼就能看出这套风格长什么样。截图在编辑态里上传、删除、调整顺序，和文本一样进草稿，保存时生效、放弃时撤销。

## 设计要点

- **存储**：风格目录（正式版本和草稿）新增子目录 `screenshots/`。文件名由服务端生成：`<三位序号>-<内容 sha256 前 12 位>.webp`，例如 `001-3fa2c9e01b7d.webp`。按文件名排序就是显示顺序，第一张是封面。名字里带内容哈希有两个用处：浏览器可以放心缓存；判断草稿有没有改动时，比较文件名列表就够了。
- **上传处理**：只接受 PNG、JPEG、WebP（用 Pillow 识别实际格式，不信任扩展名和 Content-Type）。单张原始文件 ≤ 10 MB，像素数 ≤ 5000 万；处理时按 EXIF 方向校正，取第一帧，长边缩到 ≤ 1920，统一编码为 WebP（quality 85）。每套风格最多 12 张。
- **文本模型不变**：`StyleFiles` 仍然只装 UTF-8 文本。`_read_tree` 跳过 `screenshots/`，截图由单独的函数列出。所以凡是只消费文本的地方都不用改：校验 `validate_style_files`、agent 工具 `validate_style`、创建项目时复制到 `style/`（`read_style_files`）、导入脚本。项目工作区里不会出现截图。
- **草稿流程**：打开草稿时从正式版本复制截图；保存时把截图和文本一起原子装进正式版本；放弃时整个草稿删掉，截图的改动也就撤销了；`dirty` 判断要把截图文件名列表也算进去；复制风格时截图一起复制；删除风格时整个目录删掉。
- **清理**：`prune_draft` 保留 `screenshots/` 下文件名合法的普通文件，其余（符号链接、子目录、名字不合法的文件）删掉并报告。`validate_tree` 和保存时，如果截图目录里有不合法的东西，就报成问题。
- **agent**：风格对话的可写范围不变（`references/*`、`exemplars/*`、`STYLE.md`），agent 不能改截图。
- **接口**：
  - 列表加 `cover`（封面文件名或 null；从未保存的新风格取草稿里的封面）。
  - 详情 `StyleOut` 加 `screenshots`（文件名列表），草稿状态 `DraftStatusOut` 加 `screenshots`。
  - 读正式版本的截图：`GET /api/styles/{id}/screenshots/{name}`；读草稿里的截图：`GET /api/styles/{id}/draft/screenshots/{name}`。
  - 草稿上传：`POST /api/styles/{id}/draft/screenshots`（multipart，字段 `file`，追加到末尾，返回 `DraftStatusOut`）。
  - 草稿删除：`DELETE /api/styles/{id}/draft/screenshots/{name}`（返回 `DraftStatusOut`）。
  - 草稿排序：`PUT /api/styles/{id}/draft/screenshots/order`（body `{"names": [...]}`，必须正好是当前全部文件名的一个排列，否则 422；返回 `DraftStatusOut`）。
  - 改动类请求在有对话轮次时一律 409，和现有草稿接口一样。
- **前端**：
  - 卡片顶部显示 16:9 封面（`object-fit: cover`），没有截图时显示中性占位。
  - 详情态显示一行缩略图，点开用 Dialog 看大图。
  - 编辑态在 `StyleMetaForm` 下面加一块截图区：上传按钮、拖入文件、⌘V 粘贴；每张图可以删除、左移、右移、设为封面。

## 范围

**包含：**

- `studio.styles` 新模块 `screenshots`（图片规范化、文件名规则、列出与复制），以及 `store` 里的草稿和正式版本流程。
- `api/styles.py` 的 5 个新端点和 3 个响应字段，`api/schemas.py`。
- 前端：endpoints、queries、`useStyleDraft`、`StyleCard`、`StyleDetailView`、`StyleEditView`，新组件 `StyleScreenshots.vue`。
- ADR 0022；更新 `ARCHITECTURE.md`、`QUALITY.md`。

**不包含：**

- 截图复制进项目工作区，或者在提示词里让 agent 参考截图。
- 给截图加说明文字或标题。
- 拖拽排序（用左移、右移、设为封面按钮代替）。
- 旧项目风格库的截图迁移（旧项目没有截图）。
- 生成单独的缩略图文件（统一转成长边 ≤ 1920 的 WebP 之后体积已经足够小，本地使用不需要）。

## 验收标准

- [ ] AC1：在编辑态上传 PNG、JPEG、WebP 截图（按钮、拖入、粘贴三种方式），草稿里出现 WebP 文件；非图片、超过 10 MB、超过 12 张时返回 422，界面显示原因（验证方式：store/API 单测；L4 实际操作三种方式各一次）
- [ ] AC2：保存后，卡片上的封面就是第一张截图；没有截图的风格显示占位，卡片高度一致（验证方式：组件单测；L4 截图）
- [ ] AC3：删除、左移、右移、设为封面都只改草稿；保存后生效，「放弃修改」后正式版本的截图原样不变；只改截图时草稿显示为有改动（`dirty`）（验证方式：store 单测；L4）
- [ ] AC4：复制风格时截图一起复制；删除风格时截图目录一起删掉；创建项目后，项目 `style/` 里没有 `screenshots/`（验证方式：store/API 单测）
- [ ] AC5：AI 对话轮次运行中，上传、删除、排序返回 409，编辑态截图区只读；agent 用 Bash 在 `screenshots/` 里放的符号链接、子目录或名字不合法的文件，每轮结束后被清掉（验证方式：API 单测、`prune_draft` 单测）
- [ ] AC6：读截图的接口拒绝不合法的文件名（含 `..`、符号链接），返回 400 或 404（验证方式：API 单测）
- [ ] AC7：ADR 0022、`ARCHITECTURE.md`、`QUALITY.md` 已更新，`make check` 为绿

## 任务

<!-- 状态：待开始 / 进行中 / 完成 / 阻塞 -->

### T1：`styles.screenshots` 模块与 ADR（完成）

- **目标**：图片规范化和文件名规则做成纯能力层里的独立单元。
- **涉及文件**：新建 `backend/src/studio/styles/screenshots.py`、`backend/tests/styles/test_screenshots.py`、`docs/decisions/0022-风格目录允许截图.md`；`layout.py` 加常量 `SCREENSHOTS_DIR = "screenshots"`。
- **接口与要点**：
  - 常量：`MAX_SCREENSHOTS = 12`、`MAX_UPLOAD_BYTES = 10 * 1024 * 1024`、`MAX_PIXELS = 50_000_000`、`MAX_EDGE = 1920`。
  - `class ScreenshotError(ValueError)`：错误消息用中文。
  - `normalize_image(data: bytes) -> bytes`：用 Pillow 打开；格式不是 PNG/JPEG/WebP、解码失败、超出像素上限时抛 `ScreenshotError`（像素数在 `Image.open` 之后、`load()` 之前用 `size` 检查，防解压炸弹）；`ImageOps.exif_transpose` → 取第一帧 → 转 RGB/RGBA → `thumbnail((MAX_EDGE, MAX_EDGE))` → WebP quality 85。
  - `is_screenshot_name(name: str) -> bool`：匹配 `^\d{3}-[0-9a-f]{12}\.webp$`。
  - `screenshot_name(index: int, data: bytes) -> str`：`f"{index + 1:03d}-{sha256(data)[:12]}.webp"`。
  - `list_screenshots(root: Path) -> tuple[list[str], list[str]]`：返回（合法文件名按名排序，问题列表）。目录不存在时返回空列表。符号链接、子目录、名字不合法的文件、超过 `MAX_SCREENSHOTS` 张，都记为问题。
  - `renumbered(names: list[str]) -> list[tuple[str, str]]`：按给定顺序算出（旧名，新名）的对应关系，序号重排，哈希部分保留。
  - ADR 0022：记录这次决定。风格目录允许 `screenshots/` 下的二进制文件；`StyleFiles` 仍然只装文本；截图不进项目；文件名带哈希。备选方案「截图存在草稿流程之外，改动立即生效」已经被负责人否决，写明否决理由。
- **测试**（先写）：PNG、JPEG、WebP 都能转成 WebP，长边被缩放；带 EXIF 方向的 JPEG 被转正；GIF、文本、截断的 PNG 抛 `ScreenshotError`；超像素的图（构造一张大尺寸 PNG 头）在解码前就被拒；`list_screenshots` 对符号链接、子目录、坏名字、第 13 张的报告；`renumbered` 保留哈希部分。
- **完成标准**：模块测试通过；import-linter 的 `styles` 契约仍然通过（Pillow 是第三方库，不违反契约）。
- **验证命令**：`make check`

### T2：store 接入截图（完成）

- **目标**：草稿和正式版本的全部流程都带上截图。
- **涉及文件**：`backend/src/studio/styles/store.py`、`backend/tests/styles/test_store.py`。
- **接口与要点**：
  - `_read_tree` 遇到顶层的 `screenshots/` 目录时跳过（不读进 `StyleFiles`，也不报不允许的路径）；`validate_tree` 和 `save_draft` 把 `list_screenshots` 的问题列表合并进去。
  - `_install(files, final, *, screenshots_from: Path | None = None)`：在临时目录里写好文本之后，把 `screenshots_from` 下的合法截图逐个复制进去，然后再 `_swap`。`open_draft`、`save_draft`、`duplicate_style`（经由 `import_style(..., screenshots_from=...)`）都传源目录。
  - `StyleSummary.cover: str | None`、`StyleDetail.screenshots: list[str]`、`DraftStatus.screenshots: list[str]`；`dirty` 还要比较两边的截图文件名列表。
  - 新增草稿操作，都先经过和 `_draft_file` 同样的符号链接检查：
    - `add_draft_screenshot(data_dir, style_id, data: bytes) -> str`：调用方传进来的已经是规范化之后的 WebP 字节；数量满了抛 `StyleValidationError`；新文件名的序号是现有数量 + 1；先写临时文件再 `os.replace`。
    - `delete_draft_screenshot(data_dir, style_id, name) -> None`：删掉后把剩下的重新编号。
    - `reorder_draft_screenshots(data_dir, style_id, names: list[str]) -> None`：`names` 不是当前列表的一个排列时抛 `StyleValidationError`；两阶段改名（先改成临时名，再改成最终名），避免中途撞名。
    - `screenshot_path(data_dir, style_id, name, *, draft: bool) -> Path`：名字不合法抛 `StylePathError`，文件不存在或是符号链接抛 `StyleNotFoundError`。
  - `prune_draft`：`screenshots/` 是目录且不是符号链接时，只清理里面不合法的条目（报告为 `screenshots/<name>`）；`screenshots` 是普通文件或符号链接时整个删掉。
- **测试**（先写）：打开草稿时截图被复制；只改截图时 `dirty` 为真；保存之后正式版本的截图和草稿一致；放弃之后正式版本不变；复制风格时截图被复制；`read_style_files` 不含截图；删除后剩下的被重新编号；排序的参数不是排列时被拒、正常排序生效；第 13 张被拒；`prune_draft` 清理符号链接、子目录、坏名字，合法截图保留；`cover` 取第一张，新风格取草稿里的。
- **完成标准**：新测试和既有的 store 测试全绿。
- **验证命令**：`make check`

### T3：API 端点（进行中）

- **目标**：5 个端点和 3 个响应字段。
- **涉及文件**：`backend/src/studio/api/styles.py`、`backend/src/studio/api/schemas.py`、`backend/tests/api/test_styles.py`、`backend/tests/api/test_projects.py`（只加一条断言：项目 `style/` 里没有截图）。
- **接口与要点**：
  - schemas：`StyleSummaryOut.cover: str | None`、`StyleOut.screenshots: list[str]`、`DraftStatusOut.screenshots: list[str]`、`ScreenshotOrder(BaseModel, extra="forbid") { names: list[str] }`。
  - 上传：先检查 `content-length`（超过 `MAX_UPLOAD_BYTES` 加 64 KB 余量就直接 422），然后 `await request.form()`，读 `file` 字段，最多读 `MAX_UPLOAD_BYTES + 1` 字节（超了就 422）。规范化放在线程里做：`await asyncio.to_thread(normalize_image, data)`。全部 `await` 结束之后，再调用 `_ensure_idle`，接着同步调用 `store.add_draft_screenshot`，两者之间没有 `await`。`ScreenshotError` 映射为 422。
  - 删除、排序：先 `_ensure_idle`，再调用 store，返回 `_draft_out(...)`。
  - 读取两个端点：`FileResponse(path, media_type="image/webp")`，`Cache-Control: private, max-age=31536000, immutable`（文件名带内容哈希）。名字不合法返回 400，文件不存在返回 404。
  - 注意路由顺序：`/styles/{id}/draft/screenshots/order` 的 PUT 和 `/draft/screenshots/{name}` 的 DELETE 方法不同，不会冲突；要用测试确认 `order` 不会被当成截图文件名。
- **测试**（先写）：上传 PNG 得到 WebP，状态里出现文件名；上传文本或空文件 → 422；上传超大文件 → 422；轮次在跑时上传、删除、排序都返回 409（沿用现有测试里让 `is_subject_busy` 返回真的办法）；读取接口对 `..%2F`、坏名字返回 400，对不存在的文件返回 404，正常时 `content-type` 为 `image/webp`；列表的 `cover` 和详情的 `screenshots` 正确；创建项目后项目 `style/` 下没有 `screenshots`。
- **完成标准**：API 测试全绿。
- **验证命令**：`make check`

### T4：前端接口、卡片封面、详情缩略图（待开始）

- **目标**：AC2 的显示部分。
- **涉及文件**：`frontend/src/types/api.ts`（手写类型，照抄后端新增的三个字段）、`frontend/src/api/endpoints.ts`、`endpoints.spec.ts`、`frontend/src/features/styles/styleFiles.ts`、`styleFiles.spec.ts`、`StyleCard.vue`、`StyleCard.spec.ts`、`StyleDetailView.vue`、`StyleDetailView.spec.ts`。
- **接口与要点**：
  - `styleFiles.ts`：`screenshotUrl(styleId: string, name: string, opts: { draft: boolean }): string`，id 和 name 都编码，带上 `BASE_URL`。
  - endpoints：`uploadStyleScreenshot(styleId, file: File): Promise<DraftStatusOut>`（复用 `uploadForm`，字段 `file`）、`deleteStyleScreenshot(styleId, name): Promise<DraftStatusOut>`、`reorderStyleScreenshots(styleId, names: string[]): Promise<DraftStatusOut>`。
  - `StyleCard`：顶部 `aspect-video` 的封面区。有 `cover` 时显示 `<img loading="lazy" class="object-cover">`（`is_new` 时用草稿的地址）；没有时显示带 `ImageOff` 图标的 `bg-muted` 占位。图片加载失败时也回落到占位。
  - `StyleDetailView`：描述下面一行缩略图（`h-20`，横向滚动），点击后用 `components/ui/dialog` 看大图，大图里可以左右切换。没有截图时这一行不显示。
- **测试**（先写）：`screenshotUrl` 的编码和草稿路径；卡片有封面时出现 `img` 且 `src` 正确，没有封面或 `error` 事件之后显示占位；详情点缩略图打开大图。
- **完成标准**：组件测试通过。
- **验证命令**：`make check`

### T5：编辑态截图区（待开始）

- **目标**：AC1、AC3、AC5 的界面部分。
- **涉及文件**：新建 `frontend/src/features/styles/StyleScreenshots.vue`、`StyleScreenshots.spec.ts`；`useStyleDraft.ts`、`useStyleDraft.spec.ts`、`StyleEditView.vue`、`StyleEditView.spec.ts`、`frontend/src/composables/queries.ts`（如果需要 mutation）。
- **接口与要点**：
  - `useStyleDraft` 新增 `screenshots: ComputedRef<string[]>`（来自草稿状态）、`screenshotError: Ref<string | null>`、`uploadScreenshots(files: File[]): Promise<void>`（逐个串行上传，跳过不是 `image/*` 的文件；每次成功都用返回的状态 `setQueryData(queryKeys.styleDraft(id))`；遇到失败就停止，并把原因写进 `screenshotError`）、`removeScreenshot(name)`、`moveScreenshot(name, to: number)`（算出新顺序后调用排序接口）。409 的处理和文本写入一致：清空错误，然后 `invalidateStyleDraft`。
  - `StyleScreenshots.vue`：props `{ styleId, names, readonly, uploading }`，emits `upload(files)`、`remove(name)`、`move(name, to)`。显示缩略图网格；第一张标「封面」；每张有删除、左移、右移、「设为封面」（`move(name, 0)`）；一个上传按钮（隐藏的 `<input type=file accept="image/png,image/jpeg,image/webp" multiple>`）；整块区域支持 `dragover`/`drop`；数量达到 12 张时禁用上传并说明原因；`readonly` 时全部禁用。
  - `StyleEditView`：在 `StyleMetaForm` 下面放 `StyleScreenshots`；在根容器上监听 `paste`，剪贴板里有图片文件、并且编辑区没有锁定时上传（不 `preventDefault` 文本粘贴）；`screenshotError` 显示在截图区下方。
- **测试**（先写）：`uploadScreenshots` 跳过非图片文件、串行上传、出错就停；`moveScreenshot` 算出的顺序正确（包括设为封面）；409 时让草稿重新获取；`StyleScreenshots` 的按钮在 `readonly` 时禁用、第一张有「封面」标记、第一张没有左移、最后一张没有右移、满 12 张时上传按钮禁用；`StyleEditView` 粘贴图片时调用上传。
- **完成标准**：单测通过。
- **验证命令**：`make check`

### T6：自验证与文档（待开始）

- **目标**：拿到 AC1–AC7 的证据。
- **涉及文件**：本计划的「验证记录」、`docs/ARCHITECTURE.md`（`styles` 行、`api` 行、`features/styles/` 行）、`docs/quality/QUALITY.md`。
- **要点**：`make dev` 后，在内置浏览器里做 L4：给 2 套风格各上传 2–3 张截图（三种方式都试一次）、调整顺序、保存、放弃各做一遍；截图风格库首页（卡片有封面）、详情、编辑态；AI 对话运行中确认截图区只读。用 `curl` 验证 409 和 400/404。
- **完成标准**：每条 AC 都有证据；`make check` 为绿；交给负责人验收。
- **验证命令**：`make check`

## 进度

- 2026-10-08 — T1 完成：`styles/screenshots.py`、25 个单测、ADR 0022，`make check` 绿
- 2026-10-08 — T2 完成：`store.py` 接入截图（草稿/保存/复制/清理/dirty/封面），新增 `tests/styles/test_store_screenshots.py`

## 下一步

- 做 T3：先在 `backend/tests/api/test_styles.py` 写截图端点用例，再改 `api/styles.py`、`api/schemas.py`。store 的新函数：`add_draft_screenshot`、`delete_draft_screenshot`、`reorder_draft_screenshots`、`screenshot_path(..., draft=)`；`StyleSummary.cover`、`StyleDetail.screenshots`、`DraftStatus.screenshots`。

## 决策记录

- 2026-10-08 — 截图走草稿流程（负责人选择），不复制进项目（负责人选择）。
- 2026-10-08 — 排序靠文件名前缀，不另建索引文件：目录就是唯一的事实来源，和 ADR 0019「不要两个事实来源」一致。
- 2026-10-08 — 统一转 WebP，不保存原图：卡片、详情、编辑三处共用一份，体积可控；风格截图只用来识别风格，不需要原始画质。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 无
