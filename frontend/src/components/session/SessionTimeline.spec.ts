import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { TimelineItem } from '@/composables/useSessionStream'
import type { TurnOut } from '@/types/api'
import SessionTimeline from './SessionTimeline.vue'
import { snapshotEventLabel } from './snapshotReason'

const ok = { text: 'ok', isError: false, truncated: false, images: [] }
const items: TimelineItem[] = [
  { kind: 'user_message', turnId: 't1', text: '你好' },
  { kind: 'thinking', turnId: 't1', text: '想', streaming: false },
  { kind: 'tool_call', turnId: 't1', callId: 'c1', name: 'Read', args: { file_path: 'a.md' }, result: ok },
  { kind: 'text', turnId: 't1', text: '读完了', streaming: false },
]

const settle = async () => {
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 50))
  await flushPromises()
}

function render(runningTurnId: string | null, list = items) {
  return mount(SessionTimeline, {
    props: { items: list, runningTurnId, turns: new Map(), projectId: null, sessionId: 's1' },
  })
}

describe('SessionTimeline', () => {
  it('用户消息、活动组、助手文本按顺序渲染', async () => {
    const wrapper = render(null)
    await settle()
    const text = wrapper.text()

    expect(text.indexOf('1 次工具调用')).toBeGreaterThan(-1)
    expect(text.indexOf('你好')).toBeLessThan(text.indexOf('1 次工具调用'))
    expect(text.indexOf('1 次工具调用')).toBeLessThan(text.indexOf('读完了'))
  })

  it('运行中的末尾组展开；turn 结束后自动折叠', async () => {
    const running = items.slice(0, 3)
    const wrapper = render('t1', running)
    expect(wrapper.findAll('[data-testid="activity-row"]')).toHaveLength(2)

    await wrapper.setProps({ runningTurnId: null })
    await flushPromises()

    expect(wrapper.findAll('[data-testid="activity-row"]')).toHaveLength(0)
  })

  it('用户手动展开的组不会被自动折叠', async () => {
    const wrapper = render(null)
    await wrapper.get('[data-testid="activity-header"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="activity-row"]')).toHaveLength(2)

    await wrapper.setProps({ items: [...items] })
    await flushPromises()

    expect(wrapper.findAll('[data-testid="activity-row"]')).toHaveLength(2)
  })

  describe('回复操作栏', () => {
    const turnOut = (id: string, status = 'done'): TurnOut => ({
      id,
      session_id: 's1',
      user_message: '你好',
      status,
      start_snapshot_id: null,
      end_snapshot_id: null,
      usage: { input_tokens: 1000, output_tokens: 500 },
      cost_usd: null,
      error: null,
      never_started: false,
      created_at: new Date(2026, 0, 1, 22, 53).toISOString(),
      updated_at: new Date(2026, 0, 1, 22, 53, 6).toISOString(),
    })
    const texts: TimelineItem[] = [
      { kind: 'user_message', turnId: 't1', text: '你好' },
      { kind: 'text', turnId: 't1', text: '第一段', streaming: false },
      { kind: 'tool_call', turnId: 't1', callId: 'c1', name: 'Read', args: { file_path: 'a.md' }, result: ok },
      { kind: 'text', turnId: 't1', text: '第二段', streaming: false },
      { kind: 'snapshot', turnId: 't1', snapshotId: 's', reason: 'turn', created: true },
    ]
    const mountWith = (runningTurnId: string | null, status = 'done') =>
      mount(SessionTimeline, {
        props: {
          items: texts,
          runningTurnId,
          turns: new Map([['t1', turnOut('t1', status)]]),
          projectId: null,
          sessionId: 's1',
        },
      })

    it('每个 turn 只在最后一段助手文本后出现一次', async () => {
      const wrapper = mountWith(null)
      await settle()

      expect(wrapper.findAll('[data-testid="reply-footer"]')).toHaveLength(1)
      const html = wrapper.html()
      expect(html.indexOf('第二段')).toBeLessThan(html.indexOf('reply-footer'))
      // 操作栏在助手文本之后、本轮的快照提示之前。
      expect(html.indexOf('reply-footer')).toBeLessThan(
        html.indexOf(snapshotEventLabel('turn', true)),
      )
    })

    it('turn 还在运行时不显示', async () => {
      const wrapper = mountWith('t1', 'running')
      await flushPromises()

      expect(wrapper.find('[data-testid="reply-footer"]').exists()).toBe(false)
    })
  })
})
