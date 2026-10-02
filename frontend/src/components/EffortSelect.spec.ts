import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EffortSelect from './EffortSelect.vue'

describe('EffortSelect', () => {
  it('列出三档，显示当前档位的说明', () => {
    const w = mount(EffortSelect, { props: { id: 'e', modelValue: 'low' } })

    expect(w.findAll('option').map((o) => o.text())).toEqual(['快速', '均衡', '深入'])
    expect(w.get('[data-testid="effort-hint"]').text()).toContain('先跑通流程')
  })

  it('选择后更新 v-model', async () => {
    const w = mount(EffortSelect, { props: { id: 'e', modelValue: 'medium' } })

    await w.get('select').setValue('high')

    expect(w.emitted('update:modelValue')).toEqual([['high']])
  })

  it('disabled 时选择器不可用', () => {
    const w = mount(EffortSelect, { props: { id: 'e', modelValue: 'medium', disabled: true } })

    expect(w.get('select').attributes('disabled')).toBeDefined()
  })
})
