import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RailToggleButton from './RailToggleButton.vue'

describe('RailToggleButton', () => {
  it('折叠时是「展开快照栏」、未按下；点击发出 toggle', async () => {
    const w = mount(RailToggleButton, { props: { collapsed: true } })
    const btn = w.get('[data-testid="open-snapshots"]')
    expect(btn.attributes('aria-label')).toBe('展开快照栏')
    expect(btn.attributes('aria-pressed')).toBe('false')
    await btn.trigger('click')
    expect(w.emitted('toggle')).toHaveLength(1)
  })

  it('展开时是「收起快照栏」、按下态', () => {
    const w = mount(RailToggleButton, { props: { collapsed: false } })
    const btn = w.get('[data-testid="open-snapshots"]')
    expect(btn.attributes('aria-label')).toBe('收起快照栏')
    expect(btn.attributes('aria-pressed')).toBe('true')
  })
})
