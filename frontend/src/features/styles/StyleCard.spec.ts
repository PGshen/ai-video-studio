import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { StyleSummaryOut } from '@/types/api'
import StyleCard from './StyleCard.vue'

const style: StyleSummaryOut = {
  id: 's1',
  name: '暖纸双色',
  category: '概念传记',
  description: '暖色纸张质感的双色风格',
  reference_count: 3,
  exemplar_count: 1,
  is_default: false,
  has_draft: false,
  modified_at: '2026-10-01T00:00:00Z',
}

const render = (overrides: Partial<StyleSummaryOut> = {}) =>
  mount(StyleCard, { props: { item: { ...style, ...overrides } } })

describe('StyleCard', () => {
  it('显示名称、分类、简介和引用/金样本数量', () => {
    const w = render()
    const text = w.text()
    expect(text).toContain('暖纸双色')
    expect(text).toContain('概念传记')
    expect(text).toContain('暖色纸张质感的双色风格')
    expect(text).toContain('3 个引用 · 1 个金样本')
  })

  it('默认风格带「默认」标记；有草稿才显示「有未保存草稿」', () => {
    expect(render().text()).not.toContain('默认')
    expect(render().text()).not.toContain('有未保存草稿')
    const w = render({ is_default: true, has_draft: true })
    expect(w.get('[data-testid="style-default-s1"]').text()).toBe('默认')
    expect(w.get('[data-testid="style-draft-s1"]').text()).toBe('有未保存草稿')
  })

  it('简介为空时不渲染简介段落', () => {
    expect(render({ description: null }).find('[data-testid="style-description-s1"]').exists()).toBe(
      false,
    )
  })

  it('点卡片本身打开详情', async () => {
    const w = render()
    await w.get('[data-testid="style-card-s1"]').trigger('click')
    expect(w.emitted('open')).toEqual([[style]])
    expect(w.emitted('edit')).toBeUndefined()
  })

  it('点编辑按钮只触发编辑，不打开详情', async () => {
    const w = render()
    await w.get('[data-testid="style-edit-s1"]').trigger('click')
    expect(w.emitted('edit')).toEqual([[style]])
    expect(w.emitted('open')).toBeUndefined()
  })

  it('卡片可以用键盘打开（Enter）', async () => {
    const w = render()
    await w.get('[data-testid="style-card-s1"]').trigger('keydown', { key: 'Enter' })
    expect(w.emitted('open')).toEqual([[style]])
  })
})
