# tts-voice-management：TTS 音色管理（新增 / 删除，区分豆包 v1 / v2）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 里程碑 | 无（设置页功能迭代） |
| 设计依据 | [架构设计 §6.2 设置页「TTS 音色」](../../design/2026-09-26-architecture.md)；旧项目做法见 `../ai-video/backend/app/models/tts_config.py`、`engines/tts/volcengine.py` |
| 分支 | `tts-voice-management` |
| 批准记录 | 2026-10-10：负责人批准计划，并同意 T5 的真实试听调用 |

## 目标

设置页「语音」里的音色可以由用户新增和删除；新增时选择豆包 TTS 的版本（v1 / v2），合成和试听按音色所属版本调用对应的资源与参数。

## 范围

**包含：**

- 音色从代码里的静态映射（`voice_map.py`）改为数据库表 `tts_voices`，迁移里写入现有 6 个种子音色（含此前被隐藏的 v1 `sisi`）。
- 每个音色带版本：`doubao_1.0`（资源 `seed-tts-1.0`，请求参数 `enable_timestamp`）或 `doubao_2.0`（资源 `seed-tts-2.0`，参数 `enable_subtitle`）。这两处差异在 `volcengine.py` 里已有，改成**按音色**而不是整个引擎固定一个版本。
- API：`POST /api/tts/voices`、`DELETE /api/tts/voices/{alias}`；`GET /api/tts/voices` 返回全部音色（含版本、speaker id）。
- 所有用别名校验音色的地方（项目设置、全局默认、试听、合成）改查数据库。
- 前端「语音」页：新增音色对话框、每行删除按钮（二次确认）、版本徽标。

**不包含：**

- 编辑已有音色（改名、改 speaker id）；要改就删了重建。
- 可配置的 API key、endpoint、超时（仍用环境变量 `VOLCENGINE_TTS_API_KEY`，endpoint 固定）。
- 豆包以外的 TTS 供应商。

## 验收标准

- [ ] AC1：新增音色后立即出现在「默认音色」下拉、项目设置的音色下拉和列表里，并可试听（验证方式：API 测试 + 前端测试 + 真实试听冒烟）
- [ ] AC2：别名重复、别名格式非法、speaker id 为空、版本不是 v1/v2 时拒绝，返回 422/409 和中文原因（API 测试）
- [ ] AC3：删除被项目引用的音色，或当前全局默认音色，或最后一个音色，返回 409 并说明原因（项目数、默认）；其余可删（API 测试）
- [ ] AC4：v1 音色合成走 `seed-tts-1.0` + `enable_timestamp`，v2 走 `seed-tts-2.0` + `enable_subtitle`，同一次运行里两个版本可混用（引擎单测，断言请求头和请求体）
- [ ] AC5：迁移后现有数据库的行为不变：默认 `zizi`、已有项目的 `voice` 值仍然有效；音色删除后重启不会被种子加回来（迁移测试）
- [ ] AC6：真实 v1 音色（`sisi`）试听成功，并记录逐字时间戳的形态（冒烟，写进 `docs/references/volcengine-tts.md`）
- [ ] AC7：`make check` 为绿；在浏览器里走一遍新增 → 试听 → 删除，附截图

## 任务

### T1：音色表与仓储（完成）

- **目标**：`tts_voices` 表、迁移 `0012`、仓储函数；种子只在迁移里写一次。
- **涉及文件**：`backend/src/studio/db/models.py`、`db/migrations/versions/0012_tts_voices.py`、`db/repo/voices.py`（新）、`backend/tests/db/test_repo_voices.py`（新）
- **接口与要点**：列 `alias`（主键）、`label`、`gender`（`male`/`female`）、`speaker_id`、`engine`（`doubao_1.0`/`doubao_2.0`）、`created_at`。`list_voices`、`get_voice`、`create_voice`（校验 + 重复抛 `DuplicateVoiceError`）、`delete_voice`（引用检查抛 `VoiceInUseError`，带项目数/是否默认）。别名限制为 `^[a-z0-9_]{1,40}$`（项目设置里存的是它）。引用检查扫 `projects.settings` 里的 `voice` 和 `settings` 表的 `tts_voice`。
- **测试**：先写——种子内容、新增、重复、非法别名、删除各分支（被项目用/是默认/最后一个）、迁移在已有库上幂等。
- **完成标准**：仓储测试通过。
- **验证命令**：`uv run --project backend python scripts/tasks.py check`

### T2：引擎按音色区分版本（完成）

- **目标**：`VolcengineTTSEngine` 按请求的音色取 `speaker_id` 与版本，生成对应的资源 id 和字幕参数；去掉静态 `voice_map` 的音色数据（保留 `DEFAULT_VOICE`/`DEFAULT_SPEED` 常量）。
- **涉及文件**：`engines/tts/volcengine.py`、`engines/tts/factory.py`、`engines/tts/voice_map.py`、`engines/tts/__init__.py`、`backend/tests/engines/test_tts_engine.py`、`test_voice_list.py`
- **接口与要点**：`build_tts_engine(voices)` 接收当前音色集合（来自 T1 仓储），由调用方查库后传入；引擎本身不依赖数据库（分层规则见 ARCHITECTURE.md）。版本到资源 id 的对应放在一处常量里。`health_check` 用第一个音色。
- **测试**：先写——v1/v2 的请求头 `X-Api-Resource-Id` 与 `audio_params` 断言；未知音色报错；同一引擎实例混用两个版本。
- **完成标准**：AC4 通过。
- **验证命令**：同上

### T3：API 与引用校验（完成）

- **目标**：新增/删除接口；项目设置、全局默认、试听、`synthesize_tts` 改为查库。
- **涉及文件**：`api/tts.py`、`api/projects.py`、`api/settings.py`、`stages/narrative/synthesize_tts.py`、`api/schemas.py`、对应测试
- **接口与要点**：`POST /api/tts/voices` 请求体 `{alias, label, gender, speaker_id, engine}`，成功 201 返回音色；`DELETE` 成功 204。试听缓存键加入 `speaker_id` 与版本，避免同别名重建后读到旧音频。`VoiceOut` 增加 `speaker_id`。`_ENGINE_FACTORY` 的签名随 T2 调整，测试里的替身同步改。
- **测试**：先写——AC1–AC3 的 API 用例；项目设置/默认设置引用已删除的音色时 422。
- **完成标准**：AC1–AC3 的后端部分通过。
- **验证命令**：同上

### T4：前端「语音」页（待开始）

- **目标**：新增对话框、删除、版本徽标。
- **涉及文件**：`frontend/src/features/settings/VoicePanel.vue`、`VoiceDialog.vue`（新）、`voiceForm.ts`（新，校验）、`composables/queries.ts`、`api/` 对应客户端、`*.spec.ts`
- **接口与要点**：对话框字段：名称、别名、speaker id、性别、版本（v1 / v2，单选，附一句说明：v1 为 `*_moon_bigtts` 系列，v2 为 `*_uranus_bigtts` 系列）。删除用确认对话框，409 的原因原样显示。新增/删除后让音色相关查询失效。沿用 `ModelProfileDialog.vue` 的写法。
- **测试**：先写表单校验与面板交互的 spec。
- **完成标准**：AC1、AC3 的前端部分通过。
- **验证命令**：同上

### T5：真实验证与文档（待开始）

- **目标**：真实试听 v1 音色并记录；更新文档。
- **涉及文件**：`backend/tests/smoke/test_smoke.py`、`docs/references/volcengine-tts.md`、`docs/ARCHITECTURE.md`、`docs/quality/QUALITY.md`、`docs/plans/TODO.md`
- **接口与要点**：冒烟用 `sisi` 试听一次、再用一个新增的 v2 音色合成一次（共约 2–3 次极小调用，**会产生少量费用，需负责人在批准计划时同意**，SOP §6.7）。记录 v1 的逐字时间戳是否与 v2 同形（决定 `beat_aligner` 是否可用于 v1）。浏览器里走一遍完整流程并截图。
- **完成标准**：AC5–AC7 有证据。

## 进度

- 2026-10-10 — T1 完成：`tts_voices` 表、迁移 0012（种子 6 个）、`db/repo/voices.py`；仓储测试 24 个通过，全量 3165 通过
- 2026-10-10 — T2+T3 完成（合并成一个 commit：T2 删掉了静态音色映射，调用方必须同时改成查库，否则中间状态不绿）：引擎按音色取 speaker 与版本、`TTSVoiceSpec`、`build_tts_engine(voices)`；API 新增/删除；校验与试听缓存改查库；新增冒烟 `test_tts_voice_versions_real`（待跑）。全量 3176 通过

## 下一步

- 从 T4 开始（前端）：`frontend/src/features/settings/VoicePanel.vue` 加新增对话框、删除、版本徽标。后端接口：`POST /api/tts/voices {alias,label,gender,speaker_id,engine}`、`DELETE /api/tts/voices/{alias}`（409 的 detail 是中文原因），`GET` 返回含 `speaker_id`。先写 spec。
- 之后 T5：`make smoke SMOKE_ARGS="-k tts_voice_versions_real"`（已获批准的真实调用），把结果写进 `docs/references/volcengine-tts.md`。

## 决策记录

- 2026-10-10 — 音色别名全局唯一，而不是「引擎 + 别名」唯一 — 项目设置里只存别名（`projects.settings.voice`），保持现有数据格式不变。
- 2026-10-10 — 种子只在迁移里写入，不在启动时补 — 否则删除的内置音色重启后会复活。
- 2026-10-10 — 不做编辑 — 需求只要新增和删除；改 speaker id 会让已合成的配音与音色脱钩，删了重建更直白。
- 2026-10-10 — 被项目引用的音色不能删（而不是允许删、让项目回退默认）— 静默改变已有项目的配音比一个 409 提示更糟。
- 2026-10-10 — 保留豆包 v1 的 `sisi` 并在列表中显示 — 现在它在代码里存在但被设置页隐藏，要让「区分 v1/v2」可见、可验证。

## 意外与发现

- 旧项目把音色放在 `tts_voices` + `tts_engine_configs` 两张表里，引擎表带 api key、endpoint、超时。新项目已决定 key 只走环境变量（见 `engines/tts/factory.py` 说明），所以只迁移音色表，版本用一个字段表示。
- 现有 `volcengine.py` 已经支持 v1/v2 的参数差异，但是整个引擎实例只能是其中一个版本；`factory` 固定 `seed-tts-2.0`。

- `backend/tests/scripts/test_tasks_dev.py::test_belongs_to_project[info7-darwin-True]` 在 Windows 上失败（把 macOS 路径当 Windows 路径解析）；在 main 上同样失败，与本计划无关，登记到 TODO。

## 阻塞

- 无

## 验证记录

- 无
