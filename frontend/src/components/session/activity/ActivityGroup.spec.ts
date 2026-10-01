import { effectScope, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ThinkingItem, ToolCallItem } from '@/composables/useSessionStream'
import type { ActivityGroupBlock } from '@/components/session/groupTimeline'
import ActivityGroup from './ActivityGroup.vue'
import { useDisclosure } from './useDisclosure'

const done = { text: '读到了内容', isError: false, truncated: false, images: [] }
const failed = { text: '文件不存在', isError: true, truncated: false, images: [] }

function tool(
  callId: string,
  name: string,
  args: Record<string, unknown>,
  result?: ToolCallItem['result'],
): ToolCallItem {
  return { kind: 'tool_call', turnId: 't1', callId, name, args, ...(result ? { result } : {}) }
}
const thought = (text: string, streaming = false): ThinkingItem => ({
  kind: 'thinking',
  turnId: 't1',
  text,
  streaming,
})
const grp = (entries: ActivityGroupBlock['entries'], running = false): ActivityGroupBlock => ({
  kind: 'activity',
  turnId: 't1',
  key: 't1:1',
  entries,
  running,
})

function render(group: ActivityGroupBlock, turnEnded = true) {
  const disclosure = effectScope().run(() => useDisclosure(ref('s1')))!
  const wrapper = mount(ActivityGroup, {
    props: { group, turnEnded, disclosure, projectId: null },
  })
  return { wrapper, disclosure }
}
const header = (w: ReturnType<typeof render>['wrapper']) => w.get('[data-testid="activity-header"]')
const rows = (w: ReturnType<typeof render>['wrapper']) => w.findAll('[data-testid="activity-row"]')

describe('ActivityGroup 组头', () => {
  it('只有思考：已思考；运行中：思考中…', () => {
    expect(header(render(grp([thought('想')])).wrapper).text()).toContain('已思考')
    expect(header(render(grp([thought('想', true)], true), false).wrapper).text()).toContain(
      '思考中…',
    )
  })

  it('有工具：N 次工具调用；运行中：运行中 · 第 N 次工具调用', () => {
    const entries = [thought('想'), tool('c1', 'Read', { file_path: 'a.md' }, done), tool('c2', 'Read', { file_path: 'b.md' }, done)]

    expect(header(render(grp(entries)).wrapper).text()).toContain('2 次工具调用')
    expect(header(render(grp(entries, true), false).wrapper).text()).toContain(
      '运行中 · 第 2 次工具调用',
    )
  })
})

describe('ActivityGroup 折叠', () => {
  const entries = [tool('c1', 'Read', { file_path: 'style/STYLE.md' }, done)]

  it('历史组默认折叠，点组头展开后显示行', async () => {
    const { wrapper } = render(grp(entries))
    expect(rows(wrapper)).toHaveLength(0)

    await header(wrapper).trigger('click')
    await flushPromises()

    expect(rows(wrapper)).toHaveLength(1)
    expect(wrapper.text()).toContain('读取')
    expect(wrapper.text()).toContain('style/STYLE.md')
  })

  it('运行中的组默认展开', () => {
    const { wrapper } = render(grp(entries, true), false)

    expect(rows(wrapper)).toHaveLength(1)
  })

  it('用户手动折叠运行中的组后保持折叠', async () => {
    const { wrapper, disclosure } = render(grp(entries, true), false)

    await header(wrapper).trigger('click')
    await flushPromises()

    expect(disclosure.isOpen('t1:1', true)).toBe(false)
    expect(rows(wrapper)).toHaveLength(0)
  })
})

describe('ActivityGroup 行', () => {
  async function opened(group: ActivityGroupBlock, turnEnded = true) {
    const result = render(group, turnEnded)
    // 运行中的组默认就是展开的，只有折叠着的才需要点开。
    if (rows(result.wrapper).length === 0) {
      await header(result.wrapper).trigger('click')
      await flushPromises()
    }
    return result
  }

  it('行默认折叠；点击行头展开后显示参数与结果', async () => {
    const { wrapper } = await opened(
      grp([tool('c1', 'create_idea', { title: '冰箱门为什么难拉开' }, done)]),
    )
    expect(wrapper.text()).not.toContain('读到了内容')

    await rows(wrapper)[0]!.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('title')
    expect(wrapper.text()).toContain('读到了内容')
  })

  it('出错的工具行默认展开并带 error 状态', async () => {
    const { wrapper } = await opened(grp([tool('c1', 'Read', { file_path: 'a.md' }, failed)]))

    expect(rows(wrapper)[0]!.attributes('data-status')).toBe('error')
    expect(wrapper.text()).toContain('文件不存在')
  })

  it('没有结果：turn 还在跑是 running，turn 已结束显示「已中断」', async () => {
    const running = await opened(grp([tool('c1', 'Bash', { command: 'sleep 9' })], true), false)
    expect(rows(running.wrapper)[0]!.attributes('data-status')).toBe('running')

    const ended = await opened(grp([tool('c1', 'Bash', { command: 'sleep 9' })]))
    expect(rows(ended.wrapper)[0]!.attributes('data-status')).toBe('interrupted')
    expect(ended.wrapper.text()).toContain('已中断')
  })

  it('思考行：折叠态显示首句，展开显示全文；流式时标题是「思考中」', async () => {
    const { wrapper } = await opened(grp([thought('先看看文件。\n再决定怎么改。')]))
    expect(rows(wrapper)[0]!.text()).toContain('思考')
    expect(rows(wrapper)[0]!.text()).toContain('先看看文件。')
    expect(wrapper.text()).not.toContain('再决定怎么改。')

    await rows(wrapper)[0]!.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('再决定怎么改。')

    const streaming = await opened(grp([thought('想中', true)], true), false)
    expect(rows(streaming.wrapper)[0]!.text()).toContain('思考中')
  })

  it('思考正文里的原始 HTML 当文本显示，不产生 script / img', async () => {
    const { wrapper } = await opened(grp([thought('先看<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>')]))

    await rows(wrapper)[0]!.get('button').trigger('click')
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 50))
    await flushPromises()

    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<script>alert(1)</script>')
  })
})
