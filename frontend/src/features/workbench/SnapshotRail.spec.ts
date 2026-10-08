import { mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createQueryState, snap } from './snapshotTestSupport'

const state = vi.hoisted(() => ({ current: null as unknown as ReturnType<typeof createQueryState> }))
vi.mock('@/composables/queries', async () => {
  const support = await import('./snapshotTestSupport')
  state.current = support.createQueryState()
  return support.fakeQueries(state.current)
})
vi.mock('./SnapshotTimeline.vue', () => ({
  default: { name: 'SnapshotTimeline', render: () => h('div', { 'data-testid': 'timeline' }) },
}))

import SnapshotRail from './SnapshotRail.vue'

const mountRail = (collapsed: boolean, narrow = false) =>
  mount(SnapshotRail, { props: { projectId: 'p1', busy: false, collapsed, narrow } })

describe('SnapshotRail', () => {
  beforeEach(() => {
    Object.assign(state.current, createQueryState())
    state.current.snapshots.value = [snap('s1', 'init'), snap('s2')]
  })

  it('展开：标题、快照数、收起按钮和时间线', () => {
    const w = mountRail(false)
    expect(w.text()).toContain('快照')
    expect(w.get('[data-testid="snapshot-count"]').text()).toBe('2')
    expect(w.find('[data-testid="timeline"]').exists()).toBe(true)
    expect(w.get('[data-testid="toggle-snapshots"]').attributes('aria-label')).toBe('收起快照栏')
  })

  it('折叠：整栏隐藏但保持挂载（展开入口在画布右上角；再展开时状态还在）', () => {
    const w = mountRail(true)
    const rail = w.get('[data-testid="snapshot-rail"]')
    expect((rail.element as HTMLElement).style.display).toBe('none')
  })

  it('窄屏（上下堆叠、始终展开）：不显示收起按钮，因为点了也不会有反应', () => {
    const w = mountRail(false, true)
    expect(w.find('[data-testid="snapshot-rail"]').exists()).toBe(true)
    expect(w.find('[data-testid="toggle-snapshots"]').exists()).toBe(false)
  })

  it('点按钮发出 toggle', async () => {
    const w = mountRail(false)
    await w.get('[data-testid="toggle-snapshots"]').trigger('click')
    expect(w.emitted('toggle')).toHaveLength(1)
  })

  it('没有快照时数量显示 0，不隐藏', () => {
    state.current.snapshots.value = []
    expect(mountRail(false).get('[data-testid="snapshot-count"]').text()).toBe('0')
  })
})
