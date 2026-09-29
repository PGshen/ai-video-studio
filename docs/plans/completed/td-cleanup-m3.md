# M3 后技术债清理（TD-36 / TD-6 / TD-30 / TD-31 / TD-37 / TD-28）

## 元信息

| 项 | 值 |
|---|---|
| 状态 | 已完成 |
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

- [x] AC1 TD-30、TD-31 修复并有测试（dev.sh 用脚本级检查）
- [x] AC2 TD-6：产物目录外的变化不再让下游 stale，前言无空提示
- [x] AC3 TD-36：旁白/音色/语速改动后画布显示"已过期"，前后端哈希一致
- [x] AC4 TD-37：`<audio>` 直连文件端点可跳转
- [x] AC5 tech-debt.md 与 QUALITY.md 已更新，`make check` 为绿

## 验证命令

- `make check`
- L4：浏览器打开叙事画布验证 AC3、AC4

## 进度

- [x] T1（TD-30、TD-31）
- [x] T2（TD-6）
- [x] T3（TD-36）
- [x] T4（TD-37）
- [x] T5（收尾）

## 下一步

无（计划已完成，剩余债见 tech-debt.md；TD-27 等未纳入本计划）。

## 决策记录

- T2：`build_preamble` 本来就会过滤文件级 diff 为空的上游变更，所以前言不用改；TD-6 剩下的只有 `finalize` 的 stale 判断。stale 比较用上游阶段的 `artifact_dirs()` 做前缀过滤（叙事阶段的产物目录包含 `timing.json` 和 `audio/`，所以只改配音也会让动画阶段 stale，这是有意的）。
- T2：所基于的快照缺失时保守按"有变化"处理。
- T3：改为在 timing 条目里直接记 `narration`、`voice`、`speed` 原值，而不是 `narration_hash`。原因：前端要在同步的 `computed` 里比较，浏览器的 SHA-256 是异步的，纯 TS 实现又要多维护一份；旁白文本本来就很小，明文还便于排查。旧条目没有这些字段时不判过期。前端的当前音色/语速取自项目设置（`voice`、`speech_rate`），默认值与后端一致（`zizi`、1.0）；项目还没加载出来时不判过期。
- T3：叙事定稿的提示条把"配音已过期"算进不能定稿的原因，后端 `finalize` 仍不强制（与设计 §5.2 现状一致）。

## 意外与发现

- TD-37 换成 `FileResponse` 后，响应带了 `ETag`/`Last-Modified` 但没有 `Cache-Control`，浏览器按启发式缓存，agent 或用户刚改完的 `timing.json` 在画布里还是旧的（L4 中 TD-36 的"配音已过期"迟迟不出现才发现）。端点加 `Cache-Control: no-cache` 并加测试；这是换 `FileResponse` 引入的回归，不是原有问题。
- TD-6 的前言部分本来就不需要改：`build_preamble` 对文件级 diff 为空的上游变更已经过滤。
- `test_narrative_flow.py` 原来断言真实 `timing.json` 的键与 M2 动画 fixture 完全一致，TD-36 新增三个键后改为"fixture 的键是子集，多出来的正好是 `narration`/`voice`/`speed`"。

## 阻塞

无。

## 验证记录

- `make check`（2026-09-29，分支 `td-cleanup-m3`）：全部通过；后端 760 passed / 21 deselected，前端 vitest 192 passed。
- L4（浏览器，开发库里的 M3 演示项目）：
  - TD-37：点击第 2 个 beat 后 `<audio>.currentTime` ≈ 4.55s（beat 起点 4.45s），`seekable` 覆盖全长，`src` 直接是文件端点 URL。
  - TD-36：手动给演示项目 `timing.json` 的 `s-hook` 条目写入不同的 `narration` 后刷新，镜头卡片显示"配音已过期"，提示条为"1 个镜头还没有配音；1 个镜头的配音已过期（旁白、音色或语速在配音后改过），需要重新配音"；验证后已恢复演示数据。
  - `Cache-Control`：改写文件后不刷新页面的 `fetch` 立即拿到新内容。
- TD-30：`bash -n scripts/dev.sh` 通过；`set -euo pipefail` 下 `if ! read ... < <(false)` 会走到显式的错误分支。
