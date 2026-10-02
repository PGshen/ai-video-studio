import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TurnOut } from '@/types/api'
import ReplyFooter from './ReplyFooter.vue'

afterEach(() => vi.unstubAllGlobals())

function turn(overrides: Partial<TurnOut> = {}): TurnOut {
  const created = new Date(2026, 0, 1, 22, 53)
  return {
    id: 't1',
    session_id: 's1',
    user_message: '你好',
    status: 'done',
    start_snapshot_id: null,
    end_snapshot_id: null,
    usage: { input_tokens: 50000, output_tokens: 1000 },
    cost_usd: null,
    error: null,
    never_started: false,
    created_at: created.toISOString(),
    updated_at: new Date(created.getTime() + 6000).toISOString(),
    ...overrides,
  }
}
const mountFooter = (turns: Map<string, TurnOut>) =>
  mount(ReplyFooter, { props: { turnId: 't1', text: '回复内容', turns } })

describe('ReplyFooter', () => {
  it('显示用量、用时和时间', () => {
    const w = mountFooter(new Map([['t1', turn()]]))

    expect(w.text()).toContain('用量 51K tok')
    expect(w.text()).toContain('用时 6 秒')
    expect(w.text()).toContain('22:53')
  })

  it('有缓存拆分时显示输出和输入，不再只给一个吓人的总数', () => {
    const w = mountFooter(
      new Map([
        [
          't1',
          turn({
            usage: { input_tokens: 229_000, output_tokens: 24_200, cache_read_tokens: 221_000 },
          }),
        ],
      ]),
    )

    expect(w.text()).toContain('用量 输出 24K · 输入 229K（缓存 221K）')
    expect(w.text()).not.toContain('253K')
  })

  it('用量缺失时只省略用量', () => {
    const w = mountFooter(new Map([['t1', turn({ usage: null })]]))

    expect(w.text()).not.toContain('用量')
    expect(w.text()).toContain('用时 6 秒')
  })

  it('turn 缺失或还没结束时整行不显示', () => {
    expect(mountFooter(new Map()).find('[data-testid="reply-footer"]').exists()).toBe(false)
    expect(
      mountFooter(new Map([['t1', turn({ status: 'running' })]])).find('[data-testid="reply-footer"]').exists(),
    ).toBe(false)
  })

  it('点复制把回复文本写进剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const w = mountFooter(new Map([['t1', turn()]]))

    await w.get('[data-testid="reply-copy"]').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('回复内容')
  })
})
