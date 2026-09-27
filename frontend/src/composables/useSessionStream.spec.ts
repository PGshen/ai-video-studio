import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStream, type TimelineItem, type ToolCallItem } from '@/composables/useSessionStream'
import type { SessionDetailOut } from '@/types/api'
import type { StreamEvent } from '@/types/events'

const { getSessionMock, openStreamMock } = vi.hoisted(() => ({
  getSessionMock: vi.fn(),
  openStreamMock: vi.fn(),
}))

vi.mock('@/api/endpoints', () => ({
  getSession: getSessionMock,
  sessionStreamUrl: (id: string) => `/api/sessions/${id}/stream`,
}))

vi.mock('@/api/sse', () => ({
  openStream: openStreamMock,
}))

function sessionDetail(overrides: Partial<SessionDetailOut> = {}): SessionDetailOut {
  return {
    id: 's1',
    project_id: 'p1',
    stage: 'topic',
    model_profile_id: 'm1',
    runtime: 'fake',
    sdk_ref: null,
    status: 'idle',
    is_active: true,
    title: null,
    turns: [],
    ...overrides,
  }
}

/** 挂载一个只调用 `useSessionStream` 的壳组件，返回它暴露的响应式状态和
 * 捕获到的 `openStream` 回调，方便测试直接调用 `onEvent`/`onStatus`。 */
async function setup(sessionId: string | null) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const idRef = ref<string | null>(sessionId)
  let exposed: ReturnType<typeof useSessionStream> | undefined

  const Comp = defineComponent({
    setup() {
      exposed = useSessionStream(idRef)
      return () => h('div')
    },
  })

  const wrapper = mount(Comp, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  await flushAsync()
  return { wrapper, idRef, queryClient, get result() {
    return exposed!
  } }
}

async function flushAsync() {
  await nextTick()
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

beforeEach(() => {
  getSessionMock.mockReset()
  openStreamMock.mockReset()
})

function frame(type: StreamEvent['type'], payload: Record<string, unknown>): StreamEvent {
  return { type, payload } as StreamEvent
}

describe('useSessionStream', () => {
  it('挂载时用 GET /sessions/{id} 加载历史 turn 状态，再打开 SSE', async () => {
    getSessionMock.mockResolvedValue(
      sessionDetail({
        turns: [
          {
            id: 't1',
            session_id: 's1',
            user_message: '你好',
            status: 'done',
            start_snapshot_id: null,
            end_snapshot_id: 'snap1',
            usage: null,
            cost_usd: 0,
            error: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:01Z',
          },
        ],
      }),
    )

    const { result } = await setup('s1')

    expect(getSessionMock).toHaveBeenCalledWith('s1')
    expect(openStreamMock).toHaveBeenCalledTimes(1)
    const [url, options] = openStreamMock.mock.calls[0]!
    expect(url).toBe('/api/sessions/s1/stream')
    expect(options.afterSeq).toBe(0)
    expect(result.turnStatus.value).toEqual({ turnId: 't1', status: 'done', error: null })
    // 挂载时还没有任何 SSE 事件到达，用户消息要等第一条属于这个 turn 的
    // 事件到达才插入（见 composable 文档里的排列规则）。
    expect(result.items.value).toEqual([])
  })

  it('见到某个 turn 的第一条事件时插入对应的用户消息', async () => {
    getSessionMock.mockResolvedValue(
      sessionDetail({
        turns: [
          {
            id: 't1',
            session_id: 's1',
            user_message: '讲个笑话',
            status: 'running',
            start_snapshot_id: 's0',
            end_snapshot_id: null,
            usage: null,
            cost_usd: null,
            error: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ],
      }),
    )
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('text', { turn_id: 't1', text: '好的', seq: 1 }))

    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '讲个笑话' },
      { kind: 'text', turnId: 't1', text: '好的', streaming: false },
    ])
  })

  it('text_delta 累积成进行中的文本块，text 到达时整体替换', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('text_delta', { turn_id: 't1', text: '你', seq: null }))
    onEvent(frame('text_delta', { turn_id: 't1', text: '好', seq: null }))

    const items = result.items.value
    expect(items).toHaveLength(2) // user_message 占位 + 一条 streaming 文本
    const streaming = items[1] as TimelineItem & { kind: 'text' }
    expect(streaming).toMatchObject({ kind: 'text', text: '你好', streaming: true })

    onEvent(frame('text', { turn_id: 't1', text: '你好，很高兴认识你', seq: 2 }))

    expect(result.items.value).toHaveLength(2)
    expect(result.items.value[1]).toEqual({
      kind: 'text',
      turnId: 't1',
      text: '你好，很高兴认识你',
      streaming: false,
    })
  })

  it('tool_call 与 tool_result 按 call_id 配对', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(
      frame('tool_call', {
        turn_id: 't1',
        call_id: 'c1',
        name: 'write_file',
        args: { path: 'a.md' },
        seq: 1,
      }),
    )
    onEvent(
      frame('tool_result', {
        turn_id: 't1',
        call_id: 'c1',
        text: 'ok',
        truncated: false,
        is_error: false,
        images: [],
        seq: 2,
      }),
    )

    const call = result.items.value.find((i): i is ToolCallItem => i.kind === 'tool_call')
    expect(call?.result).toEqual({ text: 'ok', isError: false, truncated: false })
  })

  it('workspace_changed 让文件树/快照 query 失效', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ project_id: 'p1', turns: [] }))
    const { result, queryClient } = await setup('s1')
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('workspace_changed', { turn_id: 't1', paths: ['a.md'], seq: null }))
    await flushAsync()

    const invalidatedKeys = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)
    expect(invalidatedKeys).toContainEqual(['projects', 'p1', 'files'])
    expect(invalidatedKeys).toContainEqual(['projects', 'p1', 'snapshots'])
    void result
  })

  it('turn_status 更新当前 turn 状态', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('turn_status', { turn_id: 't2', status: 'running', error: null, seq: null }))

    expect(result.turnStatus.value).toEqual({ turnId: 't2', status: 'running', error: null })
  })

  it('sessionId 变为 null 时关闭连接并清空状态', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const abort = vi.fn()
    openStreamMock.mockImplementation((_url: string, options: { signal?: AbortSignal }) => {
      options.signal?.addEventListener('abort', abort)
    })
    const { result, idRef } = await setup('s1')

    idRef.value = null
    await flushAsync()

    expect(abort).toHaveBeenCalledTimes(1)
    expect(result.items.value).toEqual([])
    expect(result.turnStatus.value).toBeNull()
  })
})
