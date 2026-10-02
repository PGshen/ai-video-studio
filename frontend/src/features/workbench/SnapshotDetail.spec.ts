import { flushPromises, mount } from '@vue/test-utils'
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

import SnapshotDetail from './SnapshotDetail.vue'

const snapshots = [snap('s3'), snap('s2'), snap('s1', 'init')] // 最新在前
const mountDetail = (selected: string[], busy = false) =>
  mount(SnapshotDetail, { props: { projectId: 'p1', busy, snapshots, selected }, attachTo: document.body })

describe('SnapshotDetail', () => {
  beforeEach(() => {
    Object.assign(state.current, createQueryState())
    document.body.innerHTML = ''
  })

  it('没选：提示选择一个快照', () => {
    expect(mountDetail([]).text()).toContain('选择一个快照查看详情')
  })

  it('选中最早的快照：显示「初始快照」，不发起对比', () => {
    const w = mountDetail(['s1'])
    expect(w.text()).toContain('初始快照')
    expect(state.current.diffCalls.at(-1)?.from ?? null).toBeNull()
  })

  it('对比中显示加载提示', () => {
    state.current.diffPending.value = true
    expect(mountDetail(['s3']).text()).toContain('对比中…')
  })

  it('展示新增、删除的文件和每个修改文件的 diff；二进制文件不生成 diff', () => {
    state.current.diff.value = {
      added: ['a.md', 'b.md'],
      removed: ['old.md'],
      modified: [
        { path: 'brief.md', text_diff: '-a\n+b' },
        { path: 'img.png', text_diff: null },
      ],
    }
    const text = mountDetail(['s3']).text()
    expect(text).toContain('新增：a.md、b.md')
    expect(text).toContain('删除：old.md')
    expect(text).toContain('brief.md')
    expect(text).toContain('二进制文件，不生成 diff')
  })

  it('没有任何变化时明说', () => {
    state.current.diff.value = { added: [], removed: [], modified: [] }
    expect(mountDetail(['s3']).text()).toContain('与上一个快照相比没有变化')
  })

  it('选两个：标题是对比，且没有「回滚到此」', () => {
    const w = mountDetail(['s3', 's1'])
    expect(w.text()).toContain('对比')
    expect(w.text()).not.toContain('回滚到此')
  })

  it('单选：「回滚到此」二次确认后回滚到所选快照', async () => {
    const w = mountDetail(['s2'])
    await w.get('[data-testid="rollback-button"]').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('回滚到这个快照？')
    expect(state.current.rollback.calls).toEqual([])
    const confirm = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('确认回滚'))!
    confirm.click()
    await flushPromises()
    expect(state.current.rollback.calls).toEqual(['s2'])
  })

  it('agent 运行中：「回滚到此」禁用', () => {
    const w = mountDetail(['s2'], true)
    expect(w.get('[data-testid="rollback-button"]').attributes('disabled')).toBeDefined()
  })
})
