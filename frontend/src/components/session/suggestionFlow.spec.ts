import { describe, expect, it } from 'vitest'
import {
  STAGE_TITLES,
  badgeCount,
  cardActions,
  goToAction,
  prefillText,
  suggestionRoute,
} from './suggestionFlow'

describe('goToAction（点「去处理」时目标阶段的状态决定怎么走）', () => {
  it('进行中的阶段直接跳转', () => {
    expect(goToAction('active')).toEqual({ kind: 'go' })
  })

  it('已定稿或上游变更（stale）的阶段先确认并重新打开，再跳转', () => {
    expect(goToAction('finalized')).toEqual({ kind: 'reopen_then_go' })
    expect(goToAction('stale')).toEqual({ kind: 'reopen_then_go' })
  })

  it('未开放（locked）的阶段不提供，并说明原因', () => {
    const action = goToAction('locked')
    expect(action.kind).toBe('unavailable')
    expect(action.kind === 'unavailable' && action.reason).toContain('未开放')
  })

  it('阶段状态还没加载出来时不提供', () => {
    expect(goToAction(undefined).kind).toBe('unavailable')
  })
})

describe('cardActions（卡片上有哪些按钮）', () => {
  it('待处理的建议有「去处理」和「忽略」', () => {
    expect(cardActions('open', 'active')).toEqual({ go: true, dismiss: true, goDisabledReason: null })
  })

  it('目标阶段未开放时「去处理」禁用并带原因，「忽略」仍可用', () => {
    const actions = cardActions('open', 'locked')
    expect(actions.go).toBe(true)
    expect(actions.goDisabledReason).toContain('未开放')
    expect(actions.dismiss).toBe(true)
  })

  it.each(['applied', 'dismissed'] as const)('已处理/已忽略（%s）的建议没有按钮', (status) => {
    expect(cardActions(status, 'active')).toEqual({ go: false, dismiss: false, goDisabledReason: null })
  })
})

describe('prefillText', () => {
  it('写明来源阶段和建议内容，方便使用者在上游阶段直接发出去', () => {
    const text = prefillText({ from_stage: 'animation', content: 's-hook 旁白太长' })
    expect(text).toContain(STAGE_TITLES.animation)
    expect(text).toContain('s-hook 旁白太长')
  })

  it('未知阶段名原样显示', () => {
    expect(prefillText({ from_stage: 'x', content: 'c' })).toContain('x')
  })
})

describe('suggestionRoute', () => {
  it('跳到目标阶段，建议 id 放在 query 里', () => {
    expect(suggestionRoute('p1', 'narrative', 'sg1')).toBe('/projects/p1/narrative?suggestion=sg1')
  })

  it('对特殊字符编码', () => {
    expect(suggestionRoute('p#1', 'narrative', 's g')).toBe('/projects/p%231/narrative?suggestion=s%20g')
  })
})

describe('badgeCount', () => {
  it('读阶段的待处理数量，没有的阶段是 0', () => {
    expect(badgeCount({ narrative: 2 }, 'narrative')).toBe(2)
    expect(badgeCount({ narrative: 2 }, 'topic')).toBe(0)
    expect(badgeCount(undefined, 'topic')).toBe(0)
  })
})
