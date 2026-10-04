import { describe, expect, it } from 'vitest'
import {
  brainstormScope,
  projectScope,
  sameScope,
  scopeProjectId,
  scopeResetKey,
  scopeStageKey,
  styleScope,
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

  describe('风格对话范围', () => {
    it('没有项目，按风格 id 区分', () => {
      expect(styleScope('s1')).toEqual({ kind: 'style', styleId: 's1' })
      expect(scopeProjectId(styleScope('s1'))).toBeNull()
    })

    it('sameScope 比较风格 id，并和另外两种范围区分开', () => {
      expect(sameScope(styleScope('s1'), styleScope('s1'))).toBe(true)
      expect(sameScope(styleScope('s1'), styleScope('s2'))).toBe(false)
      expect(sameScope(styleScope('s1'), brainstormScope)).toBe(false)
      expect(sameScope(styleScope('s1'), projectScope('s1', 'style'))).toBe(false)
      expect(sameScope(brainstormScope, styleScope('s1'))).toBe(false)
    })

    it('scopeResetKey 随风格 id 变化，并和项目、头脑风暴的键不冲突', () => {
      expect(scopeResetKey(styleScope('s1'))).not.toBe(scopeResetKey(styleScope('s2')))
      expect(scopeResetKey(styleScope('s1'))).not.toBe(scopeResetKey(brainstormScope))
      expect(scopeResetKey(styleScope('a'))).not.toBe(scopeResetKey(projectScope('a', 'style')))
    })

    it('scopeStageKey：默认模型按阶段取——头脑风暴、风格对话各自一项，项目阶段是阶段名', () => {
      expect(scopeStageKey(brainstormScope)).toBe('brainstorm')
      expect(scopeStageKey(styleScope('s1'))).toBe('style')
      expect(scopeStageKey(projectScope('p1', 'narrative'))).toBe('narrative')
    })
  })
})
