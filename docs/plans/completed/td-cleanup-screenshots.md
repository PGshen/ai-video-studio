# td-cleanup-screenshots：风格截图遗留问题清理

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成 |
| 里程碑 | 风格库截图之后（整理） |
| 设计依据 | [style-screenshots](style-screenshots.md) 的整分支评审发现；登记表 [tech-debt.md](../../quality/tech-debt.md) 的 TD-85、TD-86 |
| 分支 | `td-cleanup-screenshots` |
| 批准记录 | 2026-10-08：负责人要求处理 style-screenshots 的遗留问题，范围按登记表里写好的建议修法；负责人验收通过，合并到 main |

## 目标

把 style-screenshots 评审留下的 TD-85、TD-86 全部处理掉：截图内容校验、序号与改名的健壮性、图片处理不再 500、上传端点的请求头与资源清理、旧风格重新导入不丢截图，并补上当时缺的测试。

## 范围

**包含：** TD-85 的四点，TD-86 的四点（见登记表原文）。

**不包含：** 歌词上传端点的同类问题（TD-83，另一个功能的代码）；浏览器里用真实键盘 ⌘V 和「AI 正在修改」的复现（工具做不到，保持「只有自动化测试证据」）。

## 验收标准

- [x] AC1：名字合法但内容不对（文本、哈希不符、过大）的截图，`prune_draft` 删除并报告，保存报 422（验证方式：`TestContentChecks`、`test_verify_screenshot_*`）
- [x] AC2：草稿里序号不连续时新增截图排在最后并整体重排；同图重复添加两张都保留；改名中途失败回到原来的顺序；写入失败不留临时文件；`screenshots` 是普通文件时是路径错误而不是 500（验证方式：`TestAddAndRenumber`）
- [x] AC3：LA 图保留透明、16 位灰度不变白、处理中的任何异常都是 `ScreenshotError`、`DecompressionBombWarning` 不外泄（验证方式：`test_screenshots.py`）
- [x] AC4：上传没有或写坏 `Content-Length` 时 422，取图响应带 `nosniff`，处理期间轮次开始仍然 409，`screenshots/` 目录是符号链接时取图 400（验证方式：`TestScreenshotHardening`）
- [x] AC5：`--overwrite` 重新导入旧风格保留用户加的截图（验证方式：`test_overwrite_keeps_the_screenshots_added_after_the_first_import`）
- [x] AC6：`fakeStyleApi` 模拟 busy 409 和 12 张上限，对应前端行为有测试；`tech-debt.md` 更新；`make check` 为绿

## 任务

### T1：后端（完成）

- **涉及文件**：`backend/src/studio/styles/screenshots.py`、`store.py`、`api/styles.py`、`db/legacy_styles.py` 及对应测试。
- **要点**：见登记表 TD-85、TD-86 的处理说明。测试先写，`TestScreenshotHardening` 的三条新行为（`nosniff`、无 `Content-Length`、写坏的 `Content-Length`）在没改端点时已确认失败。
- **验证命令**：`make check`

### T2：前端测试替身与文档（完成）

- **涉及文件**：`frontend/src/test/fakeStyleApi.ts`、`useStyleDraft.spec.ts`、`docs/quality/tech-debt.md`。
- **验证命令**：`make check`

## 进度

- 2026-10-08 — T1、T2 完成，`make check` 见验证记录

## 下一步

- 无（已验收并合并）。

## 决策记录

- 2026-10-08 — 内容校验放在 `list_screenshots(verify=True)` 里，只在保存、校验、清理时读文件；列表和 `dirty` 判断仍只看文件名，避免每次防抖写入都读全部图片。
- 2026-10-08 — 没有 `Content-Length` 的上传直接拒绝，而不是自己流式解析：浏览器的 `FormData` 和 curl 都会带这个头，没有它的请求不是正常客户端。
- 2026-10-08 — 磁盘错误（`OSError`）仍是 500，没有映射成 422：它不是用户输入的问题。回滚保证失败后目录回到原样。

## 意外与发现

- 无

## 阻塞

- 无

## 验证记录

- 2026-10-08：`make check` 全绿（后端 2754、前端 1198 个测试，ruff、pyright、import-linter、文档检查通过）。
- 先失败再通过：`verify_screenshot`、`list_screenshots(verify=True)` 在函数不存在时导入失败；`TestScreenshotHardening` 的三条新行为在没改端点时失败，改后通过；另两条（处理期间轮次开始、符号链接目录取图）本来就正确，补的是缺的覆盖。
