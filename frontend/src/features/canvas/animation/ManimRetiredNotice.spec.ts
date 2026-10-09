import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ManimRetiredNotice from './ManimRetiredNotice.vue'

describe('ManimRetiredNotice', () => {
  it('说明 Manim 已下线，并渲染标签行的操作插槽（快照栏开关）', () => {
    const w = mount(ManimRetiredNotice, { slots: { actions: '<button data-testid="rail">快照</button>' } })
    expect(w.get('[data-testid="manim-retired"]').text()).toContain('Manim 动画已下线')
    expect(w.find('[data-testid="rail"]').exists()).toBe(true)
  })
})
