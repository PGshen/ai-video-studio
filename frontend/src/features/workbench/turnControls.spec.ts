import { describe, expect, it } from 'vitest'
import { computeTurnControls, isBusyStatus } from './turnControls'

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
