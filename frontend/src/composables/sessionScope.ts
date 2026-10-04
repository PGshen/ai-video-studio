/**
 * 会话的归属范围（计划 M4 T10）：项目里某个阶段的会话、没有项目的头脑风暴会话，或者一套风格的对话。
 * 会话面板/选择器（`components/session/`）在两处复用：项目工作台和选题池的头脑风暴抽屉，
 * 靠这个类型区分查询哪一组会话、创建会话走哪个接口。纯逻辑，放在 `composables/` 让
 * `components/` 和 `features/` 都能用。
 */

export type SessionScope =
  | { kind: 'project'; projectId: string; stage: string }
  | { kind: 'brainstorm' }
  /** 一套风格的 AI 对话（没有项目；会话属于这套风格，ADR 0019）。 */
  | { kind: 'style'; styleId: string }

export const brainstormScope: SessionScope = { kind: 'brainstorm' }

export function projectScope(projectId: string, stage: string): SessionScope {
  return { kind: 'project', projectId, stage }
}

export function styleScope(styleId: string): SessionScope {
  return { kind: 'style', styleId }
}

/** 默认模型按阶段取（设置页「各阶段默认模型」）：头脑风暴、风格对话各占一项，项目阶段是阶段名。 */
export function scopeStageKey(scope: SessionScope): string {
  if (scope.kind === 'brainstorm') return 'brainstorm'
  if (scope.kind === 'style') return 'style'
  return scope.stage
}

/** 项目会话的项目 id（工具结果图片的 blob 地址要用）；头脑风暴会话没有项目，返回 `null`。 */
export function scopeProjectId(scope: SessionScope): string | null {
  return scope.kind === 'project' ? scope.projectId : null
}

export function sameScope(a: SessionScope, b: SessionScope): boolean {
  if (a.kind === 'brainstorm') return b.kind === 'brainstorm'
  if (a.kind === 'style') return b.kind === 'style' && a.styleId === b.styleId
  return b.kind === 'project' && a.projectId === b.projectId && a.stage === b.stage
}

/** 范围变化（换项目、换阶段）时用它重置选中的会话；头脑风暴固定为同一个键。 */
export function scopeResetKey(scope: SessionScope): string {
  if (scope.kind === 'brainstorm') return 'brainstorm'
  if (scope.kind === 'style') return `style:${scope.styleId.length}:${scope.styleId}`
  return `project:${scope.projectId.length}:${scope.projectId}:${scope.stage}`
}
