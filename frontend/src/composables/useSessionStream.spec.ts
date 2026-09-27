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
  // 测试只需要按 `type` 分支构造任意合法 payload；和 `api/sse.ts` 里同样的原因，
  // 没法从 `Record<string, unknown>` 静态收窄成对应联合分支，经 `unknown` 中转。
  return { type, payload } as unknown as StreamEvent
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
    expect(call?.result).toEqual({ text: 'ok', isError: false, truncated: false, images: [] })
  })

  it('workspace_changed 让文件树/快照 query 失效', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ project_id: 'p1', turns: [] }))
    const { result, queryClient } = await setup('s1')
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('workspace_changed', { turn_id: 't1', paths: ['a.md'], seq: null }))
    await flushAsync()

    // vue-query 的 `invalidateQueries` 类型上允许 `filters` 是一个返回 filters 的函数
    // （方便传 `ref`/getter），但这里的调用方（`invalidateWorkspace`）永远直接传对象
    // 字面量，测试断言时按对象形状收窄即可。
    const invalidatedKeys = invalidateSpy.mock.calls.map(
      (call) => (call[0] as { queryKey?: unknown[] } | undefined)?.queryKey,
    )
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

  it('审查回归：sessionId 在 loadHistory 完成前又变化，慢的历史结果不生效、不会多开连接', async () => {
    let resolveS1: (detail: SessionDetailOut) => void = () => {}
    const s1Promise = new Promise<SessionDetailOut>((resolve) => {
      resolveS1 = resolve
    })
    getSessionMock.mockImplementation((id: string) => {
      if (id === 's1') return s1Promise
      return Promise.resolve(sessionDetail({ id: 's2', project_id: 'p2', turns: [] }))
    })

    const { result, idRef } = await setup('s1')
    // s1 的 getSession 还没 resolve，不应该已经打开任何流。
    expect(openStreamMock).not.toHaveBeenCalled()

    idRef.value = 's2'
    await flushAsync()

    // s2 的历史已经加载完（同步 resolve），流已经打开，且只有这一条。
    expect(openStreamMock).toHaveBeenCalledTimes(1)
    const [s2Url, s2Options] = openStreamMock.mock.calls[0]!
    expect(s2Url).toBe('/api/sessions/s2/stream')
    const s2Signal = (s2Options as { signal: AbortSignal }).signal

    // 现在才让 s1 的 getSession resolve（复现"慢请求最后才回来"）。
    resolveS1(
      sessionDetail({
        id: 's1',
        project_id: 'p1',
        turns: [
          {
            id: 't-s1',
            session_id: 's1',
            user_message: '这是 s1 的消息',
            status: 'done',
            start_snapshot_id: null,
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
    await flushAsync()

    // s1 的结果必须被丢弃：没有多打开第二条连接，s2 现役连接也没被误伤。
    expect(openStreamMock).toHaveBeenCalledTimes(1)
    expect(s2Signal.aborted).toBe(false)

    const s2OnEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
    s2OnEvent(frame('text', { turn_id: 't-s2', text: 's2 的事件', seq: 1 }))

    expect(result.items.value).toHaveLength(2) // s2 的 user_message 占位 + 这条 text
    expect(result.items.value.every((i) => i.turnId !== 't-s1')).toBe(true)
  })

  it('审查回归：已过期连接的 onEvent 即使仍被调用也不会写入状态', async () => {
    getSessionMock.mockImplementation((id: string) =>
      Promise.resolve(sessionDetail({ id, project_id: `p-${id}`, turns: [] })),
    )
    const { result, idRef } = await setup('s1')
    const s1OnEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    idRef.value = 's2'
    await flushAsync()
    expect(openStreamMock).toHaveBeenCalledTimes(2)

    // 模拟真实网络里"abort 生效前，旧连接的最后几个字节已经在路上"：
    // 直接调用捕获到的 s1 回调（它对应的流已经被 disconnect 掐断，但这里
    // 强行模拟它仍然触发了一次 onEvent）。
    s1OnEvent(frame('text', { turn_id: 't-s1', text: '过期事件', seq: 1 }))

    // 世代检查应该丢弃它：不写进 items，也不影响 s2 的状态。
    expect(result.items.value.every((i) => i.turnId !== 't-s1')).toBe(true)
  })

  it('addLocalUserMessage 乐观插入用户消息，turn 的第一个事件到达时原地补上真实 turnId', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    result.addLocalUserMessage('乐观插入的问题')
    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 'local-0', text: '乐观插入的问题' },
    ])

    onEvent(frame('turn_status', { turn_id: 't1', status: 'queued', error: null, seq: null }))
    onEvent(frame('text_delta', { turn_id: 't1', text: '好的', seq: null }))

    // 占位项被原地替换成真实 turnId，不是额外插入一条、也没有留下空文本占位。
    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '乐观插入的问题' },
      { kind: 'text', turnId: 't1', text: '好的', streaming: true },
    ])
  })

  it('addLocalUserMessage 按发送顺序（FIFO）依次和到达的 turn 配对', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    result.addLocalUserMessage('第一条')
    onEvent(frame('text', { turn_id: 't1', text: '回复1', seq: 1 }))
    result.addLocalUserMessage('第二条')
    onEvent(frame('text', { turn_id: 't2', text: '回复2', seq: 2 }))

    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '第一条' },
      { kind: 'text', turnId: 't1', text: '回复1', streaming: false },
      { kind: 'user_message', turnId: 't2', text: '第二条' },
      { kind: 'text', turnId: 't2', text: '回复2', streaming: false },
    ])
  })

  it('sessionId 变化时清空乐观占位队列，避免串到下一个会话', async () => {
    getSessionMock.mockImplementation((id: string) =>
      Promise.resolve(sessionDetail({ id, project_id: `p-${id}`, turns: [] })),
    )
    const { result, idRef } = await setup('s1')
    result.addLocalUserMessage('会话 1 里发的消息')

    idRef.value = 's2'
    await flushAsync()

    const onEvent = openStreamMock.mock.calls[1]![1].onEvent as (e: StreamEvent) => void
    onEvent(frame('text', { turn_id: 't-s2', text: '新会话的回复', seq: 1 }))

    // 新会话里第一个 turn 不应该被上一个会话遗留的占位文本"认领"。
    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't-s2', text: '' },
      { kind: 'text', turnId: 't-s2', text: '新会话的回复', streaming: false },
    ])
  })

  it('removeLocalUserMessage 撤回发送失败的占位，不留空文本、不占 FIFO 队首', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    // 第一条消息的发送请求本身失败（409/网络错误），从没真正创建 turn。
    const failedId = result.addLocalUserMessage('发送失败的消息')
    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: failedId, text: '发送失败的消息' },
    ])
    result.removeLocalUserMessage(failedId)
    expect(result.items.value).toEqual([])

    // 第二条消息正常发出去，真实 turn 的第一个事件到达时应该配对到第二条
    // 的文本，而不是被撤回的第一条"污染"（FIFO 队首本来会是被撤回的那条）。
    result.addLocalUserMessage('真正发出去的消息')
    onEvent(frame('text', { turn_id: 't1', text: '收到', seq: 1 }))

    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '真正发出去的消息' },
      { kind: 'text', turnId: 't1', text: '收到', streaming: false },
    ])
  })

  it('removeLocalUserMessage 对已经被真实 turn 认领的占位是安全的 no-op', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    const placeholderId = result.addLocalUserMessage('已经配对成功的消息')
    onEvent(frame('text', { turn_id: 't1', text: '回复', seq: 1 }))

    // 这条占位已经被 't1' 认领、原地换过 turnId 了；用旧的 placeholderId
    // 撤回不应该误删真实的 't1' 用户消息。
    result.removeLocalUserMessage(placeholderId)

    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '已经配对成功的消息' },
      { kind: 'text', turnId: 't1', text: '回复', streaming: false },
    ])
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
