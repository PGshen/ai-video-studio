import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EditModeToggle from './EditModeToggle.vue'

const mountToggle = (mode: 'view' | 'edit', busy = false, unavailable = false) =>
  mount(EditModeToggle, { props: { mode, busy, unavailable }, attachTo: document.body })

describe('EditModeToggle', () => {
  it('当前模式的按钮 aria-pressed 为真', () => {
    const w = mountToggle('view')
    expect(w.get('[data-testid="mode-view"]').attributes('aria-pressed')).toBe('true')
    expect(w.get('[data-testid="mode-edit"]').attributes('aria-pressed')).toBe('false')
  })

  it('点编辑发出 update:mode=edit，点渲染发出 view', async () => {
    const w = mountToggle('view')
    await w.get('[data-testid="mode-edit"]').trigger('click')
    expect(w.emitted('update:mode')).toEqual([['edit']])
    await w.setProps({ mode: 'edit' })
    await w.get('[data-testid="mode-view"]').trigger('click')
    expect(w.emitted('update:mode')?.[1]).toEqual(['view'])
  })

  it('agent 运行中：编辑按钮禁用且点击不发事件，渲染仍可点', async () => {
    const w = mountToggle('view', true)
    const edit = w.get('[data-testid="mode-edit"]')
    expect(edit.attributes('disabled')).toBeDefined()
    await edit.trigger('click')
    expect(w.emitted('update:mode')).toBeUndefined()
    expect(w.get('[data-testid="mode-view"]').attributes('disabled')).toBeUndefined()
  })

  it('agent 运行中：聚焦编辑按钮所在位置弹出「agent 运行中，只读」', async () => {
    const w = mountToggle('view', true)
    await w.get('[data-testid="mode-edit-wrap"]').trigger('focus')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(document.body.querySelector('[data-slot="tooltip-content"]')?.textContent).toContain(
      'agent 运行中，只读',
    )
  })

  it('agent 运行中：可聚焦的包装元素有角色、禁用状态和可访问名称', () => {
    const wrap = mountToggle('view', true).get('[data-testid="mode-edit-wrap"]')
    expect(wrap.attributes('role')).toBe('button')
    expect(wrap.attributes('aria-disabled')).toBe('true')
    expect(wrap.attributes('aria-label')).toContain('agent 运行中')
  })

  it('空闲且文件可用：包装元素不是可聚焦的假按钮', () => {
    const wrap = mountToggle('view').get('[data-testid="mode-edit-wrap"]')
    expect(wrap.attributes('role')).toBeUndefined()
    expect(wrap.attributes('tabindex')).toBeUndefined()
  })

  it('文件还不存在或在加载：编辑禁用且点击不发事件，说明原因', async () => {
    const w = mountToggle('view', false, true)
    const edit = w.get('[data-testid="mode-edit"]')
    expect(edit.attributes('disabled')).toBeDefined()
    await edit.trigger('click')
    expect(w.emitted('update:mode')).toBeUndefined()
    const wrap = w.get('[data-testid="mode-edit-wrap"]')
    expect(wrap.attributes('aria-label')).toContain('还没有')
    await wrap.trigger('focus')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(document.body.querySelector('[data-slot="tooltip-content"]')?.textContent).toContain('还没有')
  })
})
