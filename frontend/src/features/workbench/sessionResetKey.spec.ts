import { describe, expect, it } from 'vitest'
import { sessionResetKey } from './sessionResetKey'

describe('sessionResetKey', () => {
  it('项目和阶段都不变：键不变（不应该触发清空）', () => {
    expect(sessionResetKey('p1', 'topic')).toBe(sessionResetKey('p1', 'topic'))
  })

  it('只变阶段：键变化', () => {
    expect(sessionResetKey('p1', 'topic')).not.toBe(sessionResetKey('p1', 'narrative'))
  })

  it('只变项目、阶段名相同：键变化（审查修复的场景：项目 A/topic 切到项目 B/topic）', () => {
    expect(sessionResetKey('p1', 'topic')).not.toBe(sessionResetKey('p2', 'topic'))
  })

  it('项目和阶段都变：键变化', () => {
    expect(sessionResetKey('p1', 'topic')).not.toBe(sessionResetKey('p2', 'narrative'))
  })
})
