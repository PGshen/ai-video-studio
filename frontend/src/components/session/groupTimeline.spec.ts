import { describe, expect, it } from 'vitest'
import type { TimelineItem } from '@/composables/useSessionStream'
import { groupTimeline, type ActivityGroupBlock } from './groupTimeline'

const user = (turnId = 't1'): TimelineItem => ({ kind: 'user_message', turnId, text: '你好' })
const text = (turnId = 't1', streaming = false): TimelineItem => ({
  kind: 'text',
  turnId,
  text: '回复',
  streaming,
})
const thinking = (turnId = 't1', body = '想'): TimelineItem => ({
  kind: 'thinking',
  turnId,
  text: body,
  streaming: false,
})
const tool = (turnId = 't1', callId = 'c1'): TimelineItem => ({
  kind: 'tool_call',
  turnId,
  callId,
  name: 'Read',
  args: {},
})

const groups = (blocks: ReturnType<typeof groupTimeline>) =>
  blocks.filter((b): b is ActivityGroupBlock => b.kind === 'activity')

describe('groupTimeline', () => {
  it('同一 turn 里连续的 thinking 与 tool_call 归成一个活动组', () => {
    const blocks = groupTimeline([user(), thinking(), tool(), tool('t1', 'c2'), text()], null)

    expect(blocks.map((b) => b.kind)).toEqual(['user_message', 'activity', 'text'])
    const [group] = groups(blocks)
    expect(group!.entries.map((e) => e.kind)).toEqual(['thinking', 'tool_call', 'tool_call'])
    expect(group!.turnId).toBe('t1')
  })

  it('文本把活动组断成两组', () => {
    const blocks = groupTimeline([user(), tool(), text(), tool('t1', 'c2')], null)

    expect(blocks.map((b) => b.kind)).toEqual(['user_message', 'activity', 'text', 'activity'])
  })

  it('用户消息、notice、error、snapshot 也会断开', () => {
    const blocks = groupTimeline(
      [
        tool('t1', 'c1'),
        { kind: 'notice', turnId: 't1', noticeKind: 'x' },
        tool('t1', 'c2'),
        { kind: 'error', turnId: 't1', message: 'boom' },
        tool('t1', 'c3'),
        { kind: 'snapshot', turnId: 't1', snapshotId: 's', reason: 'turn', created: true },
        tool('t1', 'c4'),
      ],
      null,
    )

    expect(groups(blocks)).toHaveLength(4)
  })

  it('跨 turn 不合并', () => {
    const blocks = groupTimeline([tool('t1', 'c1'), tool('t2', 'c2')], null)

    expect(groups(blocks).map((g) => g.turnId)).toEqual(['t1', 't2'])
  })

  it('只有末尾的、属于运行中 turn 的组标记 running', () => {
    const blocks = groupTimeline([user(), tool('t1', 'c1'), text(), tool('t1', 'c2')], 't1')

    expect(groups(blocks).map((g) => g.running)).toEqual([false, true])
  })

  it('没有运行中的 turn，或末尾不是活动组时都不标 running', () => {
    expect(groups(groupTimeline([tool()], null)).map((g) => g.running)).toEqual([false])
    expect(groups(groupTimeline([tool('t1'), text('t1')], 't1')).map((g) => g.running)).toEqual([
      false,
    ])
    expect(groups(groupTimeline([tool('t1')], 't2')).map((g) => g.running)).toEqual([false])
  })

  it('空白思考被过滤，只剩空白思考时不产生活动组', () => {
    const blocks = groupTimeline([user(), thinking('t1', '  \n'), text()], null)

    expect(blocks.map((b) => b.kind)).toEqual(['user_message', 'text'])
  })

  it('空白思考不会把前后的工具拆成两组', () => {
    const blocks = groupTimeline([tool('t1', 'c1'), thinking('t1', ' '), tool('t1', 'c2')], null)

    expect(groups(blocks)).toHaveLength(1)
    expect(groups(blocks)[0]!.entries).toHaveLength(2)
  })

  it('每个组有稳定的 key：turn + 首条在 items 里的下标', () => {
    const blocks = groupTimeline([user(), thinking(), tool(), text(), tool('t1', 'c2')], null)

    expect(groups(blocks).map((g) => g.key)).toEqual(['t1:1', 't1:4'])
  })

  it('原样保留非活动条目（同一对象引用）', () => {
    const u = user()
    const t = text()
    const blocks = groupTimeline([u, tool(), t], null)

    expect(blocks[0]).toBe(u)
    expect(blocks[2]).toBe(t)
  })
})
