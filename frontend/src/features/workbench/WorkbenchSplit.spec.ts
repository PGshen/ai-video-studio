import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, onMounted } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const media = vi.hoisted(() => ({ narrow: null as unknown as { value: boolean } }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const original = await importOriginal<typeof import('@vueuse/core')>()
  const { ref: vueRef } = await import('vue')
  media.narrow = vueRef(false)
  return { ...original, useMediaQuery: () => media.narrow }
})

import WorkbenchSplit from './WorkbenchSplit.vue'

const mountSplit = () =>
  mount(WorkbenchSplit, {
    slots: {
      chat: '<div data-testid="chat">chat</div>',
      canvas: '<div data-testid="canvas">canvas</div>',
      rail: `<template #rail="{ collapsed, toggle }">
        <button data-testid="rail" :data-collapsed="collapsed" @click="toggle">rail</button>
      </template>`,
    },
    attachTo: document.body,
  })

// 统计挂载次数：断点切换不能把对话/画布销毁重建（画布里可能有未保存的编辑，输入框里可能有草稿）。
const mounts = { chat: 0, canvas: 0 }
const Probe = (name: 'chat' | 'canvas') =>
  defineComponent({
    setup() {
      onMounted(() => {
        mounts[name] += 1
      })
      return () => h('div', { 'data-testid': name })
    },
  })

describe('WorkbenchSplit', () => {
  beforeEach(() => {
    media.narrow.value = false
    localStorage.clear()
    // jsdom 没有布局：给分隔面板一个确定的尺寸，折叠/展开才有东西可算。
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      new DOMRect(0, 0, 1000, 600),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('三个面板，之间两个分隔条', () => {
    const w = mountSplit()
    for (const id of ['chat', 'canvas', 'rail']) expect(w.find(`[data-testid="${id}"]`).exists()).toBe(true)
    expect(w.findAll('[data-panel]')).toHaveLength(3)
    expect(w.findAll('[data-panel-resize-handle-id]')).toHaveLength(2)
  })

  it('快照栏默认折叠（等布局就绪后读，不是首次渲染的回落值）', async () => {
    const w = mountSplit()
    await flushPromises()
    expect(w.get('[data-testid="rail"]').attributes('data-collapsed')).toBe('true')
  })

  it('点 toggle 展开；卸载后重新挂载仍是展开（布局记在 localStorage）', async () => {
    const first = mountSplit()
    await flushPromises()
    await first.get('[data-testid="rail"]').trigger('click')
    await flushPromises()
    expect(first.get('[data-testid="rail"]').attributes('data-collapsed')).toBe('false')
    // reka 把布局写入 localStorage 有 100ms 的防抖。
    await new Promise((resolve) => setTimeout(resolve, 150))
    first.unmount()
    const second = mountSplit()
    await flushPromises()
    expect(second.get('[data-testid="rail"]').attributes('data-collapsed')).toBe('false')
    await second.get('[data-testid="rail"]').trigger('click')
    await flushPromises()
    expect(second.get('[data-testid="rail"]').attributes('data-collapsed')).toBe('true')
  })

  it('折叠窄条是固定的像素宽度，不随窗口宽度变（按钮不会被裁）', async () => {
    const panelGrow = async (width: number) => {
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, width, 600))
      localStorage.clear()
      const w = mountSplit()
      await flushPromises()
      const grow = Number.parseFloat((w.findAll('[data-panel]')[2]!.element as HTMLElement).style.flexGrow)
      w.unmount()
      return grow
    }
    expect((await panelGrow(1000) / 100) * 1000).toBeCloseTo(44, 0)
    expect((await panelGrow(2000) / 100) * 2000).toBeCloseTo(44, 0)
  })

  it('窄屏：分隔条隐藏、快照栏始终展开', async () => {
    media.narrow.value = true
    const w = mountSplit()
    await flushPromises()
    for (const handle of w.findAll('[data-panel-resize-handle-id]')) {
      expect(handle.classes()).toContain('max-lg:hidden')
    }
    expect(w.get('[data-testid="rail"]').attributes('data-collapsed')).toBe('false')
  })

  it('跨过断点时对话和画布不重新挂载（不丢未保存的编辑与输入草稿）', async () => {
    mounts.chat = 0
    mounts.canvas = 0
    const w = mount(WorkbenchSplit, {
      slots: { chat: h(Probe('chat')), canvas: h(Probe('canvas')), rail: '<div />' },
      attachTo: document.body,
    })
    await flushPromises()
    media.narrow.value = true
    await flushPromises()
    media.narrow.value = false
    await flushPromises()
    expect(mounts).toEqual({ chat: 1, canvas: 1 })
    w.unmount()
  })
})
