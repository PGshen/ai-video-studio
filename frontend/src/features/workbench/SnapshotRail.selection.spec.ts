import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createQueryState, snap } from './snapshotTestSupport'

const state = vi.hoisted(() => ({ current: null as unknown as ReturnType<typeof createQueryState> }))
vi.mock('@/composables/queries', async () => {
  const support = await import('./snapshotTestSupport')
  state.current = support.createQueryState()
  return support.fakeQueries(state.current)
})
vi.mock('@/components/ai-elements/code-block/utils', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ai-elements/code-block/utils')>()
  return { ...original, highlightCode: () => null }
})

import SnapshotRail from './SnapshotRail.vue'

// 与 SnapshotRail.spec 不同，这里不替换时间线：要看真实的选择状态在折叠、展开之间是否保留。
describe('SnapshotRail 折叠再展开', () => {
  beforeEach(() => {
    Object.assign(state.current, createQueryState())
    state.current.snapshots.value = [snap('s1', 'init'), snap('s2'), snap('s3')]
  })

  it('选中的快照不会因为折叠而丢失', async () => {
    const w = mount(SnapshotRail, {
      props: { projectId: 'p1', busy: false, collapsed: false, narrow: false },
      attachTo: document.body,
    })
    await w.findAll('[data-testid="snapshot-item"]')[0]!.get('button').trigger('click')
    expect(w.findAll('[data-testid="snapshot-item"]')[0]!.classes()).toContain('bg-primary/10')

    await w.setProps({ collapsed: true })
    await w.setProps({ collapsed: false })

    expect(w.findAll('[data-testid="snapshot-item"]')[0]!.classes()).toContain('bg-primary/10')
    expect(w.text()).not.toContain('选择一个快照查看详情')
  })

  it('折叠时整栏不可见', async () => {
    const w = mount(SnapshotRail, {
      props: { projectId: 'p1', busy: false, collapsed: true, narrow: false },
      attachTo: document.body,
    })
    const rail = w.find('[data-testid="snapshot-rail"]')
    expect(rail.exists() ? (rail.element as HTMLElement).style.display : 'none').toBe('none')
  })
})
