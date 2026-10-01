import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { TimelineItem } from '@/composables/useSessionStream'
import SessionTimeline from './SessionTimeline.vue'

const ok = { text: 'ok', isError: false, truncated: false, images: [] }
const items: TimelineItem[] = [
  { kind: 'user_message', turnId: 't1', text: '你好' },
  { kind: 'thinking', turnId: 't1', text: '想', streaming: false },
  { kind: 'tool_call', turnId: 't1', callId: 'c1', name: 'Read', args: { file_path: 'a.md' }, result: ok },
  { kind: 'text', turnId: 't1', text: '读完了', streaming: false },
]

function render(runningTurnId: string | null, list = items) {
  return mount(SessionTimeline, {
    props: { items: list, runningTurnId, turns: new Map(), projectId: null, sessionId: 's1' },
  })
}

describe('SessionTimeline', () => {
  it('用户消息、活动组、助手文本按顺序渲染', () => {
    const text = render(null).text()

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
})
