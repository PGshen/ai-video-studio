import { describe, expect, it } from 'vitest'
import { STAGE_TITLES } from './stageTitles'

describe('STAGE_TITLES', () => {
  it('names the two stages of the silent forms', () => {
    expect(STAGE_TITLES.concept).toBe('创意与要求')
    expect(STAGE_TITLES.produce).toBe('配乐与动画')
  })

  it('keeps the explainer stages and no longer has the beat sheet', () => {
    expect(STAGE_TITLES.topic).toBe('选题')
    expect(STAGE_TITLES.narrative).toBe('叙事')
    expect(STAGE_TITLES.music).toBe('配乐')
    expect(STAGE_TITLES.animation_html).toBe('动画')
    expect(STAGE_TITLES).not.toHaveProperty('beatsheet')
  })
})
