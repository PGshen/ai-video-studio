import { describe, expect, it } from 'vitest'
import { STAGES_WITH_OWN_ACTIONS } from './stageActions'

describe('STAGES_WITH_OWN_ACTIONS', () => {
  it('covers every stage with a dedicated canvas, so its buttons are not shown twice', () => {
    for (const stage of ['topic', 'narrative', 'music', 'animation', 'animation_html']) {
      expect(STAGES_WITH_OWN_ACTIONS).toContain(stage)
    }
  })

  it('leaves the generic-canvas stages to the page header', () => {
    expect(STAGES_WITH_OWN_ACTIONS).not.toContain('concept')
    expect(STAGES_WITH_OWN_ACTIONS).not.toContain('beatsheet')
  })
})
