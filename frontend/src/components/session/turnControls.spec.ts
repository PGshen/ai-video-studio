import { describe, expect, it } from 'vitest'
import { combineBusy, computeTurnControls, isBusyStatus } from './turnControls'

describe('computeTurnControls', () => {
  it('没有任何 turn（新会话）：输入可用，两个按钮都不显示', () => {
    expect(computeTurnControls(null)).toEqual({
      inputDisabled: false,
      showStop: false,
      showContinue: false,
    })
  })

  it.each(['queued', 'running'] as const)('%s：输入禁用，显示 [停止]', (status) => {
    expect(computeTurnControls(status)).toEqual({
      inputDisabled: true,
      showStop: true,
      showContinue: false,
    })
  })

  it.each(['interrupted', 'budget_exceeded'] as const)(
    '%s：输入仍可用（可以直接发新消息），额外显示 [继续]',
    (status) => {
      expect(computeTurnControls(status)).toEqual({
        inputDisabled: false,
        showStop: false,
        showContinue: true,
      })
    },
  )

  it.each(['done', 'failed', 'cancelled'] as const)('%s：输入可用，两个按钮都不显示', (status) => {
    expect(computeTurnControls(status)).toEqual({
      inputDisabled: false,
      showStop: false,
      showContinue: false,
    })
  })
})

describe('isBusyStatus', () => {
  it('null：不忙', () => {
    expect(isBusyStatus(null)).toBe(false)
  })

  it.each(['queued', 'running'] as const)('%s：忙', (status) => {
    expect(isBusyStatus(status)).toBe(true)
  })

  it.each(['interrupted', 'budget_exceeded', 'done', 'failed', 'cancelled'] as const)(
    '%s：不忙',
    (status) => {
      expect(isBusyStatus(status)).toBe(false)
    },
  )
})

describe('combineBusy', () => {
  it('两边都不忙 → 不忙', () => {
    expect(combineBusy(false, null)).toBe(false)
    expect(combineBusy(false, 'done')).toBe(false)
  })

  it('项目忙（比如另一个会话/另一个标签页在跑），当前会话没有 turn → 忙', () => {
    expect(combineBusy(true, null)).toBe(true)
  })

  it('项目查询还没轮询到最新状态（projectBusy 滞后为 false），但当前会话的 turn 已经在跑 → 忙', () => {
    expect(combineBusy(false, 'running')).toBe(true)
    expect(combineBusy(false, 'queued')).toBe(true)
  })

  it('两边都忙 → 忙', () => {
    expect(combineBusy(true, 'running')).toBe(true)
  })
})
