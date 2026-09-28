import { describe, expect, it } from 'vitest'
import { stageStatusStyle } from './stageStatus'

describe('stageStatusStyle', () => {
  it('locked：禁用、无角标', () => {
    expect(stageStatusStyle('locked')).toEqual({
      disabled: true,
      suffix: '',
      className: 'text-muted-foreground opacity-50',
    })
  })

  it('active：可点、无角标', () => {
    expect(stageStatusStyle('active')).toEqual({
      disabled: false,
      suffix: '',
      className: 'text-foreground font-medium',
    })
  })

  it('finalized：可点、勾角标', () => {
    expect(stageStatusStyle('finalized')).toEqual({
      disabled: false,
      suffix: '✓',
      className: 'text-foreground',
    })
  })

  it('stale：可点、警告角标', () => {
    expect(stageStatusStyle('stale')).toEqual({
      disabled: false,
      suffix: '⚠',
      className: 'text-amber-600',
    })
  })

  it('未知状态：不禁用、无角标（防御性兜底，不应在真实数据里出现）', () => {
    expect(stageStatusStyle('unknown')).toEqual({
      disabled: false,
      suffix: '',
      className: '',
    })
  })
})
