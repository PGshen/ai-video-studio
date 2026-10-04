import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { StyleSummaryOut } from '@/types/api'
import StyleSelect from './StyleSelect.vue'

const style = (overrides: Partial<StyleSummaryOut>): StyleSummaryOut => ({
  id: 'a',
  name: '暖纸双色',
  category: '概念传记',
  description: '暖色纸张质感',
  reference_count: 1,
  exemplar_count: 0,
  is_default: false,
  has_draft: false,
  is_new: false,
  modified_at: '2026-10-01T00:00:00Z',
  ...overrides,
})

describe('StyleSelect', () => {
  it('不列出从未保存的新风格', () => {
    const w = mount(StyleSelect, {
      props: { presets: [style({}), style({ id: 'n', name: '新草稿', is_new: true })], id: 'x' },
    })
    const labels = w.findAll('option').map((o) => o.text())
    expect(labels.some((l) => l.includes('新草稿'))).toBe(false)
    expect(labels.some((l) => l.includes('暖纸双色'))).toBe(true)
  })

  it('只有未保存的新风格时显示风格库为空的说明', () => {
    const w = mount(StyleSelect, {
      props: { presets: [style({ id: 'n', is_new: true })], id: 'x' },
    })
    expect(w.find('[data-testid="style-empty"]').exists()).toBe(true)
    expect(w.find('select').exists()).toBe(false)
  })
})
