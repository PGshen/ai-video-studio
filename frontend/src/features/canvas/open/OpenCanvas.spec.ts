import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { StageOut } from '@/types/api'

const state = vi.hoisted(() => ({ finalize: vi.fn(), reopen: vi.fn() }))

vi.mock('@/composables/queries', () => ({
  useFinalizeStageMutation: () => ({
    mutateAsync: state.finalize,
    isPending: ref(false),
    isError: ref(false),
    error: ref(null),
  }),
  useReopenStageMutation: () => ({
    mutateAsync: state.reopen,
    isPending: ref(false),
    isError: ref(false),
    error: ref(null),
  }),
}))

import OpenCanvas from './OpenCanvas.vue'

function stage(status: StageOut['status']): StageOut[] {
  return [{ stage: 'open', status, finalized_snapshot_id: null, based_on: {}, finalized_at: null }]
}

function mountCanvas(status: StageOut['status'], busy = false) {
  return mount(OpenCanvas, {
    props: { projectId: 'p1', stages: stage(status), busy },
    slots: {
      actions: '<button data-testid="rail-toggle">快照</button>',
      files: '<div data-testid="file-canvas" />',
    },
  })
}

beforeEach(() => {
  state.finalize.mockReset()
  state.reopen.mockReset()
})

describe('OpenCanvas（open-mode 设计 §7）', () => {
  it('只有文件画布，没有标签栏；头部是「完全自由」标记和操作插槽', () => {
    const wrapper = mountCanvas('active')

    expect(wrapper.find('[data-testid="file-canvas"]').exists()).toBe(true)
    expect(wrapper.find('[role="tablist"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="open-mode-badge"]').text()).toBe('完全自由')
    expect(wrapper.find('[data-testid="rail-toggle"]').exists()).toBe(true)
  })

  it('进行中显示「标记完成」，点了调用定稿接口', async () => {
    const wrapper = mountCanvas('active')
    expect(wrapper.find('[data-testid="reopen-open"]').exists()).toBe(false)

    await wrapper.get('[data-testid="complete-open"]').trigger('click')
    await flushPromises()

    expect(state.finalize).toHaveBeenCalledWith('open')
  })

  it('已完成显示「重新打开」，点了调用重新打开接口', async () => {
    const wrapper = mountCanvas('finalized')
    expect(wrapper.find('[data-testid="complete-open"]').exists()).toBe(false)

    await wrapper.get('[data-testid="reopen-open"]').trigger('click')
    await flushPromises()

    expect(state.reopen).toHaveBeenCalledWith('open')
  })

  it('agent 运行中按钮禁用', () => {
    const wrapper = mountCanvas('active', true)

    expect((wrapper.get('[data-testid="complete-open"]').element as HTMLButtonElement).disabled).toBe(
      true,
    )
  })
})
