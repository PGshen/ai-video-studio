import { describe, expect, it } from 'vitest'
import {
  brainstormScope,
  projectScope,
  sameScope,
  scopeProjectId,
  scopeResetKey,
} from '@/composables/sessionScope'

describe('sessionScope', () => {
  it('项目会话有 projectId，头脑风暴会话没有', () => {
    expect(scopeProjectId(projectScope('p1', 'topic'))).toBe('p1')
    expect(scopeProjectId(brainstormScope)).toBeNull()
  })

  it('sameScope 同时比较种类、项目和阶段', () => {
    expect(sameScope(projectScope('p1', 'topic'), projectScope('p1', 'topic'))).toBe(true)
    expect(sameScope(projectScope('p1', 'topic'), projectScope('p2', 'topic'))).toBe(false)
    expect(sameScope(projectScope('p1', 'topic'), projectScope('p1', 'narrative'))).toBe(false)
    expect(sameScope(projectScope('p1', 'topic'), brainstormScope)).toBe(false)
    expect(sameScope(brainstormScope, { kind: 'brainstorm' })).toBe(true)
  })

  it('scopeResetKey 在项目或阶段变化时变化，头脑风暴固定', () => {
    expect(scopeResetKey(projectScope('p1', 'topic'))).not.toBe(scopeResetKey(projectScope('p2', 'topic')))
    expect(scopeResetKey(projectScope('p1', 'topic'))).not.toBe(scopeResetKey(projectScope('p1', 'narrative')))
    expect(scopeResetKey(brainstormScope)).toBe(scopeResetKey({ kind: 'brainstorm' }))
    expect(scopeResetKey(brainstormScope)).not.toBe(scopeResetKey(projectScope('brainstorm', 'brainstorm')))
  })
})
