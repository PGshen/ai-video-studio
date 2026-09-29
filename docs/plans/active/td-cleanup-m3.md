# M3 后技术债清理（TD-36 / TD-6 / TD-30 / TD-31 / TD-37 / TD-28）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 进行中 |
| 里程碑 | M3 与 M4 之间（整理） |
| 设计依据 | [架构设计 §5.2、§5.4](../../design/2026-09-26-architecture.md)；登记表 [tech-debt.md](../../quality/tech-debt.md) |
| 分支 | `td-cleanup-m3` |
| 批准记录 | 2026-09-29：负责人要求"暂时不开始 M4，先处理技术债"，并批准按建议范围直接处理（复杂的写计划、不复杂直接做） |

## 目标

M4 之前处理掉两条会影响正确性的债（TD-36 配音过期判断、TD-6 stale 判断口径）和三条小债（TD-30、TD-31、TD-37），并关闭已不适用的 TD-28。完成后 `make check` 为绿。

## 范围

**包含：** TD-36、TD-6、TD-30、TD-31、TD-37；关闭 TD-28。

**不包含：** TD-27（沙箱 denyRead 的扩展需要真机验证，单独处理）、TD-9、TD-19、TD-29 及"没有症状"的各条，保持登记。

## 任务

### T1 TD-30 + TD-31（小修）
- `scripts/dev.sh`：`read` 失败改成显式 `if ! read ...; then ...; fi`。
- `workspace/scope.py::_prune_empty_ancestors`：去掉 `seen_dirs` 提前退出。测试：两个兄弟子树都越界还原后，共同祖先目录被清掉。

### T2 TD-6：stale 判断按上游产物目录
- `agent/stage_flow.py::finalize`：下游是否 stale 改为比较"下游 `based_on_snapshot_id` 快照"与"新定稿快照"在上游 `artifact_dirs()` 下的清单；无变化则不标 stale；已经是 stale 但内容已与所基于版本一致时回到 active。
- `agent/preamble.py::_upstream_changes`：文件级 diff 与镜头摘要都为空时不产生上游变更提示。
- 测试：上游产物目录之外的变化不触发 stale；产物目录变化仍触发；stale 后内容改回原样回到 active；前言不再出现空的上游变更。

### T3 TD-36：`narration_hash`
- `synthesize_tts`：timing 条目增加 `narration_hash`（旁白 + 音色 + 语速的 sha256）。
- 前端 `timingStatus.ts`：按当前旁白算哈希，与条目比较，不一致判"已过期"；旧条目没有该字段时沿用现有判断。画布提示条把它算进定稿条件。
- 哈希算法在前后端必须一致：后端 `sha256("{narration}\n{voice}\n{speed}")`（speed 用 `repr(float)`），前端用 `crypto.subtle` 或纯 TS 实现，先写一致性测试用例（固定输入 → 固定摘要）。

### T4 TD-37：文件端点支持 Range
- `api/files.py::read_file_endpoint` 改用 Starlette `FileResponse`（路径校验保持 `normalize_relpath` + `safe_path`），支持 Range。
- 前端 `BeatTimeline.vue` 去掉 blob 绕路，直接 `src`。L4 用浏览器验证点击 beat 后 `currentTime` 正确。

### T5 收尾
- tech-debt.md：TD-30/31/36/37/6 移到已解决（或改写剩余部分），TD-28 关闭并写明原因。
- QUALITY.md 如有相关条目同步；计划归档到 `completed/`。

## 验收标准

- [ ] AC1 TD-30、TD-31 修复并有测试（dev.sh 用脚本级检查）
- [ ] AC2 TD-6：产物目录外的变化不再让下游 stale，前言无空提示
- [ ] AC3 TD-36：旁白/音色/语速改动后画布显示"已过期"，前后端哈希一致
- [ ] AC4 TD-37：`<audio>` 直连文件端点可跳转
- [ ] AC5 tech-debt.md 与 QUALITY.md 已更新，`make check` 为绿

## 验证命令

- `make check`
- L4：浏览器打开叙事画布验证 AC3、AC4

## 进度

- [ ] T1　- [ ] T2　- [ ] T3　- [ ] T4　- [ ] T5

## 下一步

T1。

## 决策记录

（执行中补充）

## 意外与发现

（执行中补充）

## 阻塞

无。

## 验证记录

（收尾时补充）
