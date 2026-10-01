import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import type { ToolCallItem, ThinkingItem } from '@/composables/useSessionStream'
import type { ActivityGroupBlock } from '@/components/session/groupTimeline'
import { groupDefaultOpen, rowDefaultOpen, useDisclosure } from './useDisclosure'

function setup(initial: string | null = 's1') {
  const sessionId = ref<string | null>(initial)
  const scope = effectScope()
  const disclosure = scope.run(() => useDisclosure(sessionId))!
  return { sessionId, disclosure }
}

const tool = (result?: ToolCallItem['result']): ToolCallItem => ({
  kind: 'tool_call',
  turnId: 't1',
  callId: 'c1',
  name: 'Read',
  args: {},
  ...(result ? { result } : {}),
})
const thinking: ThinkingItem = { kind: 'thinking', turnId: 't1', text: '想', streaming: false }
const group = (running: boolean): ActivityGroupBlock => ({
  kind: 'activity',
  turnId: 't1',
  key: 't1:1',
  entries: [thinking],
  running,
})

describe('useDisclosure', () => {
  it('没有手动操作时用调用方给的默认值', () => {
    const { disclosure } = setup()

    expect(disclosure.isOpen('g1', true)).toBe(true)
    expect(disclosure.isOpen('g1', false)).toBe(false)
  })

  it('手动切换后以用户的状态为准，不再跟随默认值', () => {
    const { disclosure } = setup()

    disclosure.set('g1', false)
    expect(disclosure.isOpen('g1', true)).toBe(false)
    disclosure.set('g2', true)
    expect(disclosure.isOpen('g2', false)).toBe(true)
  })

  it('切换会话时清空手动状态，不串线', async () => {
    const { disclosure, sessionId } = setup('s1')
    disclosure.set('t1:1', true)

    sessionId.value = 's2'
    await nextTick()

    expect(disclosure.isOpen('t1:1', false)).toBe(false)
  })
})

describe('默认折叠规则', () => {
  it('运行中的末尾组默认展开，其余默认折叠', () => {
    expect(groupDefaultOpen(group(true))).toBe(true)
    expect(groupDefaultOpen(group(false))).toBe(false)
  })

  it('出错的工具行默认展开，成功、无结果和思考行默认折叠', () => {
    const failed = { text: 'x', isError: true, truncated: false, images: [] }
    const fine = { text: 'x', isError: false, truncated: false, images: [] }

    expect(rowDefaultOpen(tool(failed))).toBe(true)
    expect(rowDefaultOpen(tool(fine))).toBe(false)
    expect(rowDefaultOpen(tool())).toBe(false)
    expect(rowDefaultOpen(thinking)).toBe(false)
  })
})
