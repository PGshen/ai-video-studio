import { describe, expect, it } from 'vitest'
import { DEFAULT_EFFORT, EFFORT_OPTIONS, effortFromSettings } from './effortChoice'

describe('effortFromSettings', () => {
  it('合法值原样返回', () => {
    for (const option of EFFORT_OPTIONS) {
      expect(effortFromSettings({ effort: option.value })).toBe(option.value)
    }
  })

  it('缺失、不合法或设置不存在时回落到默认', () => {
    expect(effortFromSettings({})).toBe(DEFAULT_EFFORT)
    expect(effortFromSettings({ effort: 'max' })).toBe(DEFAULT_EFFORT)
    expect(effortFromSettings({ effort: 3 })).toBe(DEFAULT_EFFORT)
    expect(effortFromSettings(undefined)).toBe(DEFAULT_EFFORT)
  })

  it('默认值是选项之一', () => {
    expect(EFFORT_OPTIONS.map((o) => o.value)).toContain(DEFAULT_EFFORT)
  })
})
