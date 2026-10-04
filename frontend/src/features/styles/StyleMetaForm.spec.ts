import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StyleMetaForm from './StyleMetaForm.vue'

const meta = { name: '暖纸双色', category: '概念传记', description: '暖色纸张质感' }
const render = (props: Record<string, unknown> = {}) =>
  mount(StyleMetaForm, { props: { meta, ...props } })

describe('StyleMetaForm', () => {
  it('显示名称、分类、简介', () => {
    const w = render()
    expect((w.get('[data-testid="style-name"]').element as HTMLInputElement).value).toBe('暖纸双色')
    expect((w.get('[data-testid="style-category"]').element as HTMLInputElement).value).toBe(
      '概念传记',
    )
    expect((w.get('[data-testid="style-description"]').element as HTMLInputElement).value).toBe(
      '暖色纸张质感',
    )
  })

  it.each([
    ['style-name', { name: '新名字' }],
    ['style-category', { category: '新名字' }],
    ['style-description', { description: '新名字' }],
  ])('改 %s 只触发对应字段的 update', async (testId, patch) => {
    const w = render()
    await w.get(`[data-testid="${testId}"]`).setValue('新名字')
    expect(w.emitted('update')).toEqual([[patch]])
  })

  it('只读时输入框不可编辑', () => {
    const w = render({ readonly: true })
    for (const id of ['style-name', 'style-category', 'style-description']) {
      expect(w.get(`[data-testid="${id}"]`).attributes('disabled')).toBeDefined()
    }
  })
})
