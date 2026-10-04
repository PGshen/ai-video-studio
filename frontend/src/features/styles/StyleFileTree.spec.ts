import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StyleFileTree from './StyleFileTree.vue'

const FILES = ['STYLE.md', 'exemplars/e1.json', 'references/color.md', 'references/blueprint.md']

const render = (props: Record<string, unknown> = {}) =>
  mount(StyleFileTree, { props: { files: FILES, active: 'STYLE.md', ...props } })

describe('StyleFileTree 显示', () => {
  it('分组显示入口、引用文件和金样本，带数量', () => {
    const w = render()
    expect(w.get('[data-testid="file-STYLE.md"]').text()).toContain('STYLE.md')
    expect(w.get('[data-testid="group-references"]').text()).toContain('引用文件')
    expect(w.get('[data-testid="group-references"]').text()).toContain('2')
    expect(w.get('[data-testid="group-exemplars"]').text()).toContain('金样本')
    expect(w.get('[data-testid="file-references/color.md"]').text()).toBe('color.md')
    expect(w.get('[data-testid="file-exemplars/e1.json"]').text()).toBe('e1.json')
  })

  it('当前文件高亮', () => {
    const w = render({ active: 'references/color.md' })
    expect(w.get('[data-testid="file-references/color.md"]').attributes('aria-current')).toBe('true')
    expect(w.get('[data-testid="file-STYLE.md"]').attributes('aria-current')).toBeUndefined()
  })

  it('点文件切换当前文件', async () => {
    const w = render()
    await w.get('[data-testid="file-references/color.md"]').trigger('click')
    expect(w.emitted('update:active')).toEqual([['references/color.md']])
  })
})

describe('StyleFileTree 增删文件', () => {
  it('点「添加」输入文件名，回车后触发 add', async () => {
    const w = render()

    await w.get('[data-testid="add-references"]').trigger('click')
    await w.get('[data-testid="new-file-name"]').setValue('palette.md')
    await w.get('[data-testid="new-file-name"]').trigger('keydown', { key: 'Enter' })

    expect(w.emitted('add')).toEqual([['references', 'palette.md']])
    expect(w.find('[data-testid="new-file-name"]').exists()).toBe(false)
  })

  it('文件名不合法时显示原因，不触发 add', async () => {
    const w = render()

    await w.get('[data-testid="add-exemplars"]').trigger('click')
    await w.get('[data-testid="new-file-name"]').setValue('a.txt')
    await w.get('[data-testid="new-file-name"]').trigger('keydown', { key: 'Enter' })

    expect(w.get('[data-testid="file-name-error"]').text()).toContain('.json')
    expect(w.emitted('add')).toBeUndefined()
  })

  it('同目录重名不触发 add', async () => {
    const w = render()

    await w.get('[data-testid="add-references"]').trigger('click')
    await w.get('[data-testid="new-file-name"]').setValue('color.md')
    await w.get('[data-testid="new-file-name"]').trigger('keydown', { key: 'Enter' })

    expect(w.get('[data-testid="file-name-error"]').text()).toContain('已有')
    expect(w.emitted('add')).toBeUndefined()
  })

  it('Esc 取消添加', async () => {
    const w = render()
    await w.get('[data-testid="add-references"]').trigger('click')

    await w.get('[data-testid="new-file-name"]').trigger('keydown', { key: 'Escape' })

    expect(w.find('[data-testid="new-file-name"]').exists()).toBe(false)
    expect(w.emitted('add')).toBeUndefined()
  })

  it('删除按钮触发 remove；入口文件没有删除按钮', async () => {
    const w = render()
    expect(w.find('[data-testid="delete-STYLE.md"]').exists()).toBe(false)

    await w.get('[data-testid="delete-references/color.md"]').trigger('click')

    expect(w.emitted('remove')).toEqual([['references/color.md']])
    expect(w.emitted('update:active')).toBeUndefined()
  })

  it('只读时没有添加和删除', () => {
    const w = render({ readonly: true })
    expect(w.find('[data-testid="add-references"]').exists()).toBe(false)
    expect(w.find('[data-testid="delete-references/color.md"]').exists()).toBe(false)
  })
})
