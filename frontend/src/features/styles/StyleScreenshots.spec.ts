import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StyleScreenshots from './StyleScreenshots.vue'

const names = ['001-aaaaaaaaaaaa.webp', '002-bbbbbbbbbbbb.webp', '003-cccccccccccc.webp']

const render = (props: Record<string, unknown> = {}) =>
  mount(StyleScreenshots, { props: { styleId: 's1', names, readonly: false, uploading: false, ...props } })

describe('StyleScreenshots', () => {
  it('按顺序显示草稿里的截图，第一张标「封面」', () => {
    const w = render()
    expect(w.findAll('[data-testid^="shot-item-"] img').map((i) => i.attributes('src'))).toEqual(
      names.map((n) => `/api/styles/s1/draft/screenshots/${n}`),
    )
    expect(w.get('[data-testid="shot-item-0"]').text()).toContain('封面')
    expect(w.get('[data-testid="shot-item-1"]').text()).not.toContain('封面')
  })

  it('删除、左移、右移、设为封面分别发出对应事件', async () => {
    const w = render()
    await w.get('[data-testid="shot-remove-1"]').trigger('click')
    await w.get('[data-testid="shot-left-1"]').trigger('click')
    await w.get('[data-testid="shot-right-1"]').trigger('click')
    await w.get('[data-testid="shot-cover-2"]').trigger('click')
    expect(w.emitted('remove')).toEqual([[names[1]]])
    expect(w.emitted('move')).toEqual([
      [names[1], 0],
      [names[1], 2],
      [names[2], 0],
    ])
  })

  it('第一张没有左移和设为封面，最后一张没有右移', () => {
    const w = render()
    expect(w.find('[data-testid="shot-left-0"]').exists()).toBe(false)
    expect(w.find('[data-testid="shot-cover-0"]').exists()).toBe(false)
    expect(w.find('[data-testid="shot-right-2"]').exists()).toBe(false)
  })

  it('选择文件后发出 upload', async () => {
    const w = render()
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    const input = w.get('[data-testid="shot-input"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    expect(w.emitted('upload')).toEqual([[[file]]])
  })

  it('拖入文件发出 upload', async () => {
    const w = render()
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await w.get('[data-testid="shot-dropzone"]').trigger('drop', { dataTransfer: { files: [file] } })
    expect(w.emitted('upload')).toEqual([[[file]]])
  })

  it('只读时所有按钮和上传都禁用，拖入也不触发', async () => {
    const w = render({ readonly: true })
    for (const id of ['shot-remove-1', 'shot-left-1', 'shot-right-1', 'shot-cover-2', 'shot-add']) {
      expect(w.get(`[data-testid="${id}"]`).attributes('disabled')).toBeDefined()
    }
    await w
      .get('[data-testid="shot-dropzone"]')
      .trigger('drop', { dataTransfer: { files: [new File(['x'], 'a.png')] } })
    expect(w.emitted('upload')).toBeUndefined()
  })

  it('满 12 张时上传按钮禁用并说明原因', () => {
    const many = Array.from({ length: 12 }, (_, i) => `${String(i + 1).padStart(3, '0')}-aaaaaaaaaaaa.webp`)
    const w = render({ names: many })
    expect(w.get('[data-testid="shot-add"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('最多 12 张')
  })

  it('没有截图时给出提示', () => {
    expect(render({ names: [] }).text()).toContain('还没有截图')
  })
})
