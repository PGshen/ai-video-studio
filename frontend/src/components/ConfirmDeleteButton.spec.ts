import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/http'
import ConfirmDeleteButton from './ConfirmDeleteButton.vue'

function mountButton(action: () => Promise<unknown>) {
  return mount(ConfirmDeleteButton, {
    attachTo: document.body,
    props: { title: '删除选题？', description: '删除后不能恢复。', testId: 'del', action },
  })
}

function dialogButton(label: string): HTMLButtonElement {
  const found = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.trim() === label)
  if (!found) throw new Error(`没有「${label}」按钮`)
  return found
}

describe('ConfirmDeleteButton', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('点按钮先弹确认框，不会直接执行', async () => {
    const action = vi.fn().mockResolvedValue(undefined)
    const w = mountButton(action)

    await w.get('[data-testid="del"]').trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain('删除选题？')
    expect(action).not.toHaveBeenCalled()
    w.unmount()
  })

  it('确认后执行 action 并关闭确认框', async () => {
    const action = vi.fn().mockResolvedValue(undefined)
    const w = mountButton(action)
    await w.get('[data-testid="del"]').trigger('click')
    await flushPromises()

    dialogButton('确认删除').click()
    await flushPromises()

    expect(action).toHaveBeenCalledOnce()
    expect(document.body.textContent).not.toContain('删除后不能恢复。')
    w.unmount()
  })

  it('取消不执行 action', async () => {
    const action = vi.fn().mockResolvedValue(undefined)
    const w = mountButton(action)
    await w.get('[data-testid="del"]').trigger('click')
    await flushPromises()

    dialogButton('取消').click()
    await flushPromises()

    expect(action).not.toHaveBeenCalled()
    w.unmount()
  })

  it('失败时留在确认框里显示原因', async () => {
    const action = vi.fn().mockRejectedValue(new ApiError(409, '这张卡片已创建 1 个项目'))
    const w = mountButton(action)
    await w.get('[data-testid="del"]').trigger('click')
    await flushPromises()

    dialogButton('确认删除').click()
    await flushPromises()

    expect(document.body.textContent).toContain('这张卡片已创建 1 个项目')
    expect(document.body.textContent).toContain('删除选题？')
    w.unmount()
  })
})
