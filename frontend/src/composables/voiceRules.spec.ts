import { describe, expect, it } from 'vitest'
import { SPEED_MAX, SPEED_MIN, parseSpeed, speedError } from './voiceRules'

describe('语速范围（与后端 db/repo/settings.py 一致）', () => {
  it('范围是 0.5–2.0', () => {
    expect([SPEED_MIN, SPEED_MAX]).toEqual([0.5, 2])
  })
})

describe('parseSpeed / speedError', () => {
  it.each([
    ['1', 1],
    ['0.5', 0.5],
    ['2', 2],
    [' 1.25 ', 1.25],
  ])('%j 合法', (text, value) => {
    expect(parseSpeed(text)).toBe(value)
    expect(speedError(text)).toBeNull()
  })

  it.each(['', 'abc', '0.49', '2.01', '-1', 'NaN', 'Infinity', '1.2.3'])('%j 不合法', (text) => {
    expect(parseSpeed(text)).toBeNull()
    expect(speedError(text)).toContain('0.5')
  })
})
