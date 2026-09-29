/**
 * 会话的归属范围（计划 M4 T10）：项目里某个阶段的会话，或者没有项目的头脑风暴会话。
 * 会话面板/选择器（`components/session/`）在两处复用：项目工作台和选题池的头脑风暴抽屉，
 * 靠这个类型区分查询哪一组会话、创建会话走哪个接口。纯逻辑，放在 `composables/` 让
 * `components/` 和 `features/` 都能用。
 */

export type SessionScope =
  | { kind: 'project'; projectId: string; stage: string }
  | { kind: 'brainstorm' }

export const brainstormScope: SessionScope = { kind: 'brainstorm' }

export function projectScope(projectId: string, stage: string): SessionScope {
  return { kind: 'project', projectId, stage }
}

/** 项目会话的项目 id（工具结果图片的 blob 地址要用）；头脑风暴会话没有项目，返回 `null`。 */
export function scopeProjectId(scope: SessionScope): string | null {
  return scope.kind === 'project' ? scope.projectId : null
}

export function sameScope(a: SessionScope, b: SessionScope): boolean {
  if (a.kind === 'brainstorm' || b.kind === 'brainstorm') return a.kind === b.kind
  return a.projectId === b.projectId && a.stage === b.stage
}

/** 范围变化（换项目、换阶段）时用它重置选中的会话；头脑风暴固定为同一个键。 */
export function scopeResetKey(scope: SessionScope): string {
  return scope.kind === 'brainstorm'
    ? 'brainstorm'
    : `project:${scope.projectId.length}:${scope.projectId}:${scope.stage}`
}
