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

import SnapshotTimeline from './SnapshotTimeline.vue'

const mountTimeline = (busy = false) =>
  mount(SnapshotTimeline, { props: { projectId: 'p1', busy }, attachTo: document.body })

const items = (w: ReturnType<typeof mountTimeline>) => w.findAll('[data-testid="snapshot-item"]')

describe('SnapshotTimeline', () => {
  beforeEach(() => {
    const fresh = createQueryState()
    Object.assign(state.current, fresh)
    // 后端按创建时间升序返回。
    state.current.snapshots.value = [snap('s1', 'init'), snap('s2'), snap('s3')]
  })

  it('最新在前展示，每项显示原因标签', () => {
    const w = mountTimeline()
    expect(items(w).map((i) => i.text())).toEqual([
      expect.stringContaining('Agent 一轮'),
      expect.stringContaining('Agent 一轮'),
      expect.stringContaining('初始化'),
    ])
    expect(items(w)).toHaveLength(3)
  })

  it('时间线里不再有逐行的「回滚到此」按钮（回滚在详情区）', () => {
    const w = mountTimeline()
    expect(w.findAll('[data-testid="snapshot-item"] button')).toHaveLength(3)
    expect(w.text()).not.toContain('回滚到此')
  })

  it('没选时详情区提示选择一个快照', () => {
    expect(mountTimeline().text()).toContain('选择一个快照查看详情')
  })

  it('没有快照：提示还没有快照', () => {
    state.current.snapshots.value = []
    expect(mountTimeline().text()).toContain('还没有快照')
  })

  it('点选一个快照：高亮，详情区对比它与上一个', async () => {
    const w = mountTimeline()
    await items(w)[0]!.get('button').trigger('click')
    expect(items(w)[0]!.classes()).toContain('bg-primary/10')
    const last = state.current.diffCalls.at(-1)!
    expect({ from: last.from, to: last.to }).toEqual({ from: 's2', to: 's3' })
  })

  it('再点一次取消选中', async () => {
    const w = mountTimeline()
    await items(w)[0]!.get('button').trigger('click')
    await items(w)[0]!.get('button').trigger('click')
    expect(w.text()).toContain('选择一个快照查看详情')
  })

  it('选中的快照从列表里消失后，详情区回到提示，不残留旧 diff', async () => {
    // 先让详情区真的显示出一份 diff，再让选中的快照消失：这份旧 diff 必须一起消失。
    state.current.diff.value = { added: ['旧文件.md'], removed: [], modified: [] }
    const w = mountTimeline()
    await items(w)[0]!.get('button').trigger('click')
    expect(w.text()).toContain('新增：旧文件.md')
    state.current.snapshots.value = [snap('s1', 'init'), snap('s2')]
    await w.vm.$nextTick()
    expect(w.text()).toContain('选择一个快照查看详情')
    expect(w.text()).not.toContain('旧文件.md')
  })

  it('busy 时仍可查看详情，但提示暂不能回滚', () => {
    expect(mountTimeline(true).text()).toContain('agent 运行中，暂不能回滚')
  })
})
