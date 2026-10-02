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

const mountRail = (collapsed: boolean) =>
  mount(SnapshotRail, { props: { projectId: 'p1', busy: false, collapsed } })

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

  it('折叠：什么都不渲染（整栏隐藏，展开入口在画布右上角）', () => {
    const w = mountRail(true)
    expect(w.find('[data-testid="snapshot-rail"]').exists()).toBe(false)
    expect(w.find('[data-testid="timeline"]').exists()).toBe(false)
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
