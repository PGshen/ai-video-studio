/**
 * 计算"要不要清空当前选中的会话"的比较键（T13 审查修复）：`ProjectWorkbenchPage`
 * 原来只 `watch(stage, ...)` 清空 `sessionId`，切阶段（如选题→叙事）时能清
 * 空，但直接从项目 A 的选题阶段切到项目 B 的选题阶段（`stage` 两边都是
 * `topic`，没变）时不会触发，A 项目选中的 `sessionId` 会带进 B 项目——
 * 会话选择器 的"默认选中"逻辑只在 `sessionId` 为 `null` 时生效，带着
 * 一个属于别的项目的 `sessionId` 不会被覆盖。
 *
 * 用 `${projectId}/${stage}` 这个组合键代替单独 watch `stage`：项目或阶段
 * 任一个变了，键就变，`watch` 就会触发一次清空。纯函数，方便单测覆盖
 * "只变 stage"/"只变 projectId"/"两个都变"/"都不变" 四种组合。
 */
export function sessionResetKey(projectId: string, stage: string): string {
  return `${projectId}/${stage}`
}
