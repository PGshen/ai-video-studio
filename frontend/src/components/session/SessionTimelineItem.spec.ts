import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlainItem } from './groupTimeline'
import type { TurnOut } from '@/types/api'
import SessionTimelineItem from './SessionTimelineItem.vue'

afterEach(() => vi.unstubAllGlobals())

const assistant = (text: string, streaming = false): PlainItem => ({
  kind: 'text',
  turnId: 't1',
  text,
  streaming,
})
const user = (extra: Partial<Extract<PlainItem, { kind: 'user_message' }>> = {}): PlainItem => ({
  kind: 'user_message',
  turnId: 't1',
  text: '你好',
  ...extra,
})

function turn(created: Date): TurnOut {
  return {
    id: 't1',
    session_id: 's1',
    user_message: '你好',
    status: 'done',
    start_snapshot_id: null,
    end_snapshot_id: null,
    usage: null,
    cost_usd: null,
    error: null,
    never_started: false,
    created_at: created.toISOString(),
    updated_at: created.toISOString(),
  }
}

async function render(item: PlainItem, turns = new Map<string, TurnOut>()) {
  const wrapper = mount(SessionTimelineItem, { props: { item, projectId: null, turns } })
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 50))
  await flushPromises()
  return wrapper
}

describe('助手文本', () => {
  it('渲染 Markdown：表格和行内代码', async () => {
    const w = await render(assistant('| a | b |\n|---|---|\n| 1 | 2 |\n\n用 `ls` 查看'))

    expect(w.find('table').exists()).toBe(true)
    expect(w.find('code').text()).toBe('ls')
  })

  it('模型输出里的原始 HTML 当文本显示：不产生 script / img / 事件属性', async () => {
    const w = await render(
      assistant('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n<b onclick="x()">粗</b>'),
    )

    expect(w.find('script').exists()).toBe(false)
    expect(w.find('img').exists()).toBe(false)
    expect(w.find('b').exists()).toBe(false)
    // 文本里还会看到 `onerror=…`（当文本显示），但不能有任何元素带事件处理属性。
    const handlers = [...w.element.querySelectorAll('*')].flatMap((el) =>
      el.getAttributeNames().filter((name) => name.startsWith('on')),
    )
    expect(handlers).toEqual([])
    expect(w.text()).toContain('<script>alert(1)</script>')
  })

  it('代码块里的 HTML 照原样显示', async () => {
    const w = await render(assistant('```html\n<div class="a">x</div>\n```'))

    expect(w.text()).toContain('<div class="a">x</div>')
  })

  it('流式中显示闪烁光标，定稿后消失', async () => {
    expect((await render(assistant('写到一半', true))).find('[data-testid="stream-cursor"]').exists()).toBe(true)
    expect((await render(assistant('写完了'))).find('[data-testid="stream-cursor"]').exists()).toBe(false)
  })
})

describe('用户消息', () => {
  it('气泡下显示 turn 的创建时间（HH:mm）', async () => {
    const turns = new Map([['t1', turn(new Date(2026, 0, 1, 22, 53))]])
    const w = await render(user(), turns)

    expect(w.get('[data-testid="user-time"]').text()).toBe('22:53')
  })

  it('乐观占位还没有 turn 时用发送时间', async () => {
    const w = await render(user({ at: new Date(2026, 0, 1, 7, 5).toISOString() }))

    expect(w.get('[data-testid="user-time"]').text()).toBe('07:05')
  })

  it('既没有 turn 也没有发送时间时不显示时间，复制仍可用', async () => {
    const w = await render(user())

    expect(w.find('[data-testid="user-time"]').exists()).toBe(false)
    expect(w.find('[data-testid="user-copy"]').exists()).toBe(true)
  })

  it('点复制把消息文本写进剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const w = await render(user({ text: '看一下 README' }))

    await w.get('[data-testid="user-copy"]').trigger('click')

    expect(writeText).toHaveBeenCalledWith('看一下 README')
  })
})
