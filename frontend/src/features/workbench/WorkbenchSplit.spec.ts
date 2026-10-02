import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

describe('WorkbenchSplit', () => {
  beforeEach(() => {
    media.narrow.value = false
    localStorage.clear()
  })

  it('宽屏：对话、画布、快照栏三个面板，之间两个可拖的分隔条', () => {
    const w = mountSplit()
    for (const id of ['chat', 'canvas', 'rail']) expect(w.find(`[data-testid="${id}"]`).exists()).toBe(true)
    expect(w.findAll('[data-panel]')).toHaveLength(3)
    expect(w.findAll('[data-panel-resize-handle-id]')).toHaveLength(2)
  })

  it('快照栏默认折叠', () => {
    expect(mountSplit().get('[data-testid="rail"]').attributes('data-collapsed')).toBe('true')
  })

  it('窄屏：没有分隔条，三块都在，快照栏始终展开', () => {
    media.narrow.value = true
    const w = mountSplit()
    expect(w.findAll('[data-panel-resize-handle-id]')).toHaveLength(0)
    for (const id of ['chat', 'canvas', 'rail']) expect(w.find(`[data-testid="${id}"]`).exists()).toBe(true)
    expect(w.get('[data-testid="rail"]').attributes('data-collapsed')).toBe('false')
  })
})
