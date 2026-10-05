import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StageOut } from '@/types/api'

const mocks = vi.hoisted(() => ({
  finalize: { mutateAsync: vi.fn(), reject: false },
  reopen: { mutate: vi.fn() },
}))

vi.mock('@/composables/queries', async () => {
  const { ref: vueRef } = await import('vue')
  return {
    useFinalizeStageMutation: () => {
      const isError = vueRef(false)
      const error = vueRef<unknown>(null)
      return {
        isPending: vueRef(false),
        isError,
        error,
        mutateAsync: async (stage: string) => {
          mocks.finalize.mutateAsync(stage)
          if (mocks.finalize.reject) {
            isError.value = true
            error.value = new Error('简报没通过检查')
            throw error.value
          }
        },
      }
    },
    useReopenStageMutation: () => ({
      isPending: vueRef(false),
      isError: vueRef(false),
      error: vueRef(null),
      mutate: mocks.reopen.mutate,
    }),
  }
})

import StageFinalizeButton from './StageFinalizeButton.vue'

const stage = (status: string): StageOut => ({
  stage: 'topic',
  status,
  finalized_snapshot_id: null,
  based_on: {},
  finalized_at: null,
})

const mountButton = (status: string) =>
  mount(StageFinalizeButton, {
    props: { projectId: 'p1', stages: [stage(status)], currentStage: 'topic' },
    attachTo: document.body,
  })

describe('StageFinalizeButton', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    mocks.finalize.mutateAsync.mockClear()
    mocks.finalize.reject = false
    mocks.reopen.mutate.mockClear()
  })

  it('active 阶段只显示「定稿」', () => {
    const w = mountButton('active')
    expect(w.get('[data-testid="finalize-stage"]').text()).toContain('定稿')
    expect(w.find('[data-testid="reopen-stage"]').exists()).toBe(false)
  })

  it('stale 阶段（已定稿但上游又变了）两个按钮都显示', () => {
    const w = mountButton('stale')
    expect(w.find('[data-testid="finalize-stage"]').exists()).toBe(true)
    expect(w.find('[data-testid="reopen-stage"]').exists()).toBe(true)
  })

  it('已定稿阶段显示「重新打开」，点击直接重新打开', async () => {
    const w = mountButton('finalized')
    expect(w.find('[data-testid="finalize-stage"]').exists()).toBe(false)
    await w.get('[data-testid="reopen-stage"]').trigger('click')
    expect(mocks.reopen.mutate).toHaveBeenCalledWith('topic')
  })

  it('还没轮到的阶段什么都不显示', () => {
    const w = mountButton('locked')
    expect(w.find('button').exists()).toBe(false)
  })

  it('点「定稿」先弹确认框，确认后才提交', async () => {
    const w = mountButton('active')
    await w.get('[data-testid="finalize-stage"]').trigger('click')
    await flushPromises()
    expect(mocks.finalize.mutateAsync).not.toHaveBeenCalled()
    const confirm = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('确认定稿'))!
    confirm.click()
    await flushPromises()
    expect(mocks.finalize.mutateAsync).toHaveBeenCalledWith('topic')
  })

  it('定稿被拒绝：显示原因', async () => {
    mocks.finalize.reject = true
    const w = mountButton('active')
    await w.get('[data-testid="finalize-stage"]').trigger('click')
    await flushPromises()
    const confirm = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('确认定稿'))!
    confirm.click()
    await flushPromises()
    expect(w.get('[data-testid="stage-action-error"]').text()).toContain('定稿失败：简报没通过检查')
  })
})

describe('reopenOnly（动画阶段只能经成片定稿）', () => {
  const mountOnly = (status: string) =>
    mount(StageFinalizeButton, {
      props: { projectId: 'p1', stages: [stage(status)], currentStage: 'topic', reopenOnly: true },
    })

  it('活动阶段不显示定稿按钮', () => {
    expect(mountOnly('active').find('[data-testid="finalize-stage"]').exists()).toBe(false)
  })

  it('已定稿的阶段仍可重新打开', () => {
    const w = mountOnly('finalized')
    expect(w.find('[data-testid="reopen-stage"]').exists()).toBe(true)
    expect(w.find('[data-testid="finalize-stage"]').exists()).toBe(false)
  })

  it('过期的阶段可重新打开，但不能直接定稿', () => {
    const w = mountOnly('stale')
    expect(w.find('[data-testid="reopen-stage"]').exists()).toBe(true)
    expect(w.find('[data-testid="finalize-stage"]').exists()).toBe(false)
  })
})
