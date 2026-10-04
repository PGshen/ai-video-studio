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
    subject_id: null,
    turns: [],
    ...overrides,
  }
}

function turnFixture(status: string, id = 't1') {
  return {
    id,
    session_id: 's1',
    user_message: '你好',
    status,
    start_snapshot_id: 's0',
    end_snapshot_id: status === 'running' ? null : 'snap1',
    usage: null,
    cost_usd: null,
    error: null,
    never_started: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
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
            never_started: false,
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
    expect(result.turnStatus.value).toMatchObject({ turnId: 't1', status: 'done', error: null })
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

    const invalidatedKeys = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)
    expect(invalidatedKeys).toContainEqual(['projects', 'p1', 'files'])
    expect(invalidatedKeys).toContainEqual(['projects', 'p1', 'snapshots'])
    void result
  })

  describe('风格对话（stage=style，subject_id=风格 id）', () => {
    const styleSession = () =>
      sessionDetail({ project_id: null, stage: 'style', subject_id: 'sty1', turns: [] })

    it('workspace_changed 让这套风格的草稿（状态和文件）失效，不碰项目查询', async () => {
      getSessionMock.mockResolvedValue(styleSession())
      const { queryClient } = await setup('s1')
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      onEvent(frame('workspace_changed', { turn_id: 't1', paths: ['references/a.md'], seq: null }))
      await flushAsync()

      const keys = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)
      expect(keys).toContainEqual(['styles', 'sty1', 'draft'])
      expect(keys.some((k) => k?.[0] === 'projects')).toBe(false)
    })

    it('一轮开始和结束（turn_status）都刷新草稿状态——只读状态来自后端的 busy', async () => {
      getSessionMock.mockResolvedValue(styleSession())
      const { queryClient } = await setup('s1')
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      onEvent(frame('turn_status', { turn_id: 't1', status: 'running', error: null }))
      await flushAsync()
      expect(invalidateSpy.mock.calls.map((c) => c[0]?.queryKey)).toContainEqual([
        'styles',
        'sty1',
        'draft',
      ])
      invalidateSpy.mockClear()

      onEvent(frame('turn_status', { turn_id: 't1', status: 'done', error: null }))
      await flushAsync()
      const keys = invalidateSpy.mock.calls.map((c) => c[0]?.queryKey)
      expect(keys).toContainEqual(['styles', 'sty1', 'draft'])
      expect(keys).toContainEqual(['styles'])
    })

    it('不会像头脑风暴那样去失效选题池', async () => {
      getSessionMock.mockResolvedValue(styleSession())
      const { queryClient } = await setup('s1')
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      onEvent(frame('turn_status', { turn_id: 't1', status: 'done', error: null }))
      await flushAsync()

      expect(invalidateSpy.mock.calls.map((c) => c[0]?.queryKey)).not.toContainEqual(['ideas'])
    })

    it('项目会话的 workspace_changed 不碰风格查询', async () => {
      getSessionMock.mockResolvedValue(sessionDetail({ project_id: 'p1', turns: [] }))
      const { queryClient } = await setup('s1')
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      onEvent(frame('workspace_changed', { turn_id: 't1', paths: [], seq: null }))
      await flushAsync()

      expect(invalidateSpy.mock.calls.some((c) => c[0]?.queryKey?.[0] === 'styles')).toBe(false)
    })
  })

  it('无项目会话：create_idea/update_idea 的 tool_result 让选题池查询失效，不碰项目查询', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ project_id: null, stage: 'brainstorm', turns: [] }))
    const { queryClient } = await setup('s1')
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    for (const [callId, name] of [['c1', 'mcp__studio__create_idea'], ['c2', 'list_ideas']] as const) {
      onEvent(frame('tool_call', { turn_id: 't1', call_id: callId, name, args: {}, seq: 1 }))
      onEvent(
        frame('tool_result', {
          turn_id: 't1', call_id: callId, text: 'ok', truncated: false, is_error: false, images: [], seq: 2,
        }),
      )
      await flushAsync()
      const keys = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)
      if (name === 'list_ideas') expect(keys).toHaveLength(1) // only the create_idea one
      else expect(keys).toEqual([['ideas']])
    }
  })

  it('无项目会话：一轮结束（终态 turn_status）时让选题池查询失效；运行中不失效', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ project_id: null, stage: 'brainstorm', turns: [] }))
    const { queryClient } = await setup('s1')
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('turn_status', { turn_id: 't1', status: 'running', error: null, seq: null }))
    await flushAsync()
    expect(invalidateSpy).not.toHaveBeenCalled()

    onEvent(frame('turn_status', { turn_id: 't1', status: 'done', error: null, seq: null }))
    await flushAsync()
    expect(invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)).toEqual([['ideas']])
  })

  it('项目会话：tool_result 不会失效选题池查询', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ project_id: 'p1', turns: [] }))
    const { queryClient } = await setup('s1')
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('tool_call', { turn_id: 't1', call_id: 'c1', name: 'write_file', args: {}, seq: 1 }))
    onEvent(
      frame('tool_result', {
        turn_id: 't1', call_id: 'c1', text: 'ok', truncated: false, is_error: false, images: [], seq: 2,
      }),
    )
    await flushAsync()
    expect(invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)).not.toContainEqual(['ideas'])
  })

  it('suggestion 事件成为时间线条目，并让所有建议查询（列表、阶段角标）失效', async () => {
    getSessionMock.mockResolvedValue(sessionDetail())
    const { result, queryClient } = await setup('s1')
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(
      frame('suggestion', {
        turn_id: 't1',
        suggestion_id: 'sg1',
        from_stage: 'animation',
        to_stage: 'narrative',
        content: 's-hook 旁白太长',
        status: 'open',
        seq: 4,
      }),
    )
    await flushAsync()

    const item = result.items.value.find((i) => i.kind === 'suggestion')
    expect(item).toEqual({
      kind: 'suggestion',
      turnId: 't1',
      suggestionId: 'sg1',
      fromStage: 'animation',
      toStage: 'narrative',
      content: 's-hook 旁白太长',
    })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['suggestions'] })
  })

  it('turn_status 更新当前 turn 状态', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

    onEvent(frame('turn_status', { turn_id: 't2', status: 'running', error: null, seq: null }))

    expect(result.turnStatus.value).toMatchObject({ turnId: 't2', status: 'running', error: null })
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
      { kind: 'user_message', turnId: 'local-0', text: '乐观插入的问题', at: expect.any(String) },
    ])

    onEvent(frame('turn_status', { turn_id: 't1', status: 'queued', error: null, seq: null }))
    onEvent(frame('text_delta', { turn_id: 't1', text: '好的', seq: null }))

    // 占位项被原地替换成真实 turnId，不是额外插入一条、也没有留下空文本占位。
    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '乐观插入的问题', at: expect.any(String) },
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
      { kind: 'user_message', turnId: 't1', text: '第一条', at: expect.any(String) },
      { kind: 'text', turnId: 't1', text: '回复1', streaming: false },
      { kind: 'user_message', turnId: 't2', text: '第二条', at: expect.any(String) },
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
      { kind: 'user_message', turnId: failedId, text: '发送失败的消息', at: expect.any(String) },
    ])
    result.removeLocalUserMessage(failedId)
    expect(result.items.value).toEqual([])

    // 第二条消息正常发出去，真实 turn 的第一个事件到达时应该配对到第二条
    // 的文本，而不是被撤回的第一条"污染"（FIFO 队首本来会是被撤回的那条）。
    result.addLocalUserMessage('真正发出去的消息')
    onEvent(frame('text', { turn_id: 't1', text: '收到', seq: 1 }))

    expect(result.items.value).toEqual([
      { kind: 'user_message', turnId: 't1', text: '真正发出去的消息', at: expect.any(String) },
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
      { kind: 'user_message', turnId: 't1', text: '已经配对成功的消息', at: expect.any(String) },
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

  describe('I3：断线期间 turn 结束，重连后刷新 turn 状态', () => {
    function turn(status: string, id = 't1') {
      return {
        id,
        session_id: 's1',
        user_message: '你好',
        status,
        start_snapshot_id: 's0',
        end_snapshot_id: status === 'running' ? null : 'snap1',
        usage: null,
        cost_usd: null,
        error: null,
        never_started: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }
    }

    it('reconnecting → open 时重新 GET /sessions/{id} 覆盖 turnStatus', async () => {
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('running')] }))
      const { result } = await setup('s1')
      const onStatus = openStreamMock.mock.calls[0]![1].onStatus as (s: unknown) => void
      expect(result.turnStatus.value?.status).toBe('running')

      onStatus({ kind: 'open' })
      await flushAsync()
      expect(getSessionMock).toHaveBeenCalledTimes(1) // 首次 open 不重复拉取

      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('done')] }))
      onStatus({ kind: 'reconnecting', delayMs: 1000, reason: 'network' })
      onStatus({ kind: 'open' })
      await flushAsync()

      expect(getSessionMock).toHaveBeenCalledTimes(2)
      expect(result.turnStatus.value).toMatchObject({ turnId: 't1', status: 'done', error: null })
    })

    it('TD-19：重启后排队中的 turn 是 interrupted + neverStarted，带上原消息', async () => {
      getSessionMock.mockResolvedValueOnce(
        sessionDetail({
          turns: [
            {
              ...turn('interrupted'),
              start_snapshot_id: null,
              end_snapshot_id: null,
              error: '还在排队，尚未开始运行',
              never_started: true,
            },
          ],
        }),
      )
      const { result } = await setup('s1')

      expect(result.turnStatus.value).toMatchObject({
        status: 'interrupted',
        neverStarted: true,
        userMessage: '你好',
      })
      // No events will ever arrive for it, so its message is shown from the history.
      expect(result.items.value).toEqual([{ kind: 'user_message', turnId: 't1', text: '你好' }])
    })

    it('TD-19：收到 interrupted 的 turn_status 后重新拉取会话，拿到 neverStarted', async () => {
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('running')] }))
      const { result } = await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
      getSessionMock.mockResolvedValueOnce(
        sessionDetail({ turns: [{ ...turn('interrupted'), never_started: true }] }),
      )

      onEvent(frame('turn_status', { turn_id: 't1', status: 'interrupted', error: null }))
      await flushAsync()

      expect(getSessionMock).toHaveBeenCalledTimes(2)
      expect(result.turnStatus.value).toMatchObject({ status: 'interrupted', neverStarted: true })
    })

    it('刷新请求期间先到达的 turn_status 不被旧响应覆盖', async () => {
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('running')] }))
      const { result } = await setup('s1')
      const { onStatus, onEvent } = openStreamMock.mock.calls[0]![1] as {
        onStatus: (s: unknown) => void
        onEvent: (e: StreamEvent) => void
      }
      let resolveRefresh: (value: SessionDetailOut) => void = () => {}
      getSessionMock.mockReturnValueOnce(
        new Promise<SessionDetailOut>((resolve) => {
          resolveRefresh = resolve
        }),
      )

      onStatus({ kind: 'reconnecting', delayMs: 1000, reason: 'network' })
      onStatus({ kind: 'open' })
      onEvent(frame('turn_status', { turn_id: 't2', status: 'running', error: null }))
      resolveRefresh(sessionDetail({ turns: [turn('done')] }))
      await flushAsync()

      expect(result.turnStatus.value).toMatchObject({ turnId: 't2', status: 'running', error: null })
    })

    it('当前运行中 turn 的 snapshot 事件触发刷新', async () => {
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('running')] }))
      const { result } = await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('done')] }))

      onEvent(
        frame('snapshot', {
          turn_id: 't1',
          snapshot_id: 'snap1',
          reason: 'turn',
          created: true,
          seq: 3,
        }),
      )
      await flushAsync()

      expect(getSessionMock).toHaveBeenCalledTimes(2)
      expect(result.turnStatus.value?.status).toBe('done')
      expect(result.items.value).toContainEqual({
        kind: 'snapshot',
        turnId: 't1',
        snapshotId: 'snap1',
        reason: 'turn',
        created: true,
      })
    })

    it('已结束 turn 的历史 snapshot 回放不触发刷新', async () => {
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turn('done')] }))
      await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      onEvent(
        frame('snapshot', {
          turn_id: 't1',
          snapshot_id: 'snap1',
          reason: 'turn',
          created: true,
          seq: 3,
        }),
      )
      await flushAsync()

      expect(getSessionMock).toHaveBeenCalledTimes(1)
    })
  })

  describe('thinking', () => {
    async function start() {
      getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
      const { result } = await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
      return { result, onEvent }
    }
    const delta = (text: string, turn = 't1') =>
      frame('thinking_delta', { turn_id: turn, text, seq: null })
    const block = (text: string, seq: number, turn = 't1') =>
      frame('thinking', { turn_id: turn, text, seq })

    it('thinking_delta 累积成进行中的思考条目，thinking 到达时整体替换', async () => {
      const { result, onEvent } = await start()

      onEvent(delta('先'))
      onEvent(delta('想想'))
      expect(result.items.value[1]).toEqual({
        kind: 'thinking',
        turnId: 't1',
        text: '先想想',
        streaming: true,
      })

      onEvent(block('先想想看', 1))

      expect(result.items.value).toHaveLength(2) // 用户消息占位 + 一条思考
      expect(result.items.value[1]).toEqual({
        kind: 'thinking',
        turnId: 't1',
        text: '先想想看',
        streaming: false,
      })
    })

    it('没有先到的 delta（历史回放）时，thinking 直接追加一条', async () => {
      const { result, onEvent } = await start()

      onEvent(block('回放的思考', 1))

      expect(result.items.value.filter((i) => i.kind === 'thinking')).toEqual([
        { kind: 'thinking', turnId: 't1', text: '回放的思考', streaming: false },
      ])
    })

    it('思考、文本、工具、思考交替出现时各自成条，互不覆盖', async () => {
      const { result, onEvent } = await start()

      onEvent(block('先想', 1))
      onEvent(frame('text', { turn_id: 't1', text: '好的', seq: 2 }))
      onEvent(
        frame('tool_call', { turn_id: 't1', call_id: 'c1', name: 'Read', args: {}, seq: 3 }),
      )
      onEvent(delta('再想'))
      onEvent(block('再想一下', 4))

      expect(result.items.value.map((i) => i.kind)).toEqual([
        'user_message',
        'thinking',
        'text',
        'tool_call',
        'thinking',
      ])
      const thinking = result.items.value.filter((i) => i.kind === 'thinking')
      expect(thinking.map((i) => i.text)).toEqual(['先想', '再想一下'])
    })

    it('思考终稿到达时末尾已有进行中的文本（Claude 的事件顺序）：原地替换，不重复', async () => {
      const { result, onEvent } = await start()

      onEvent(delta('想'))
      onEvent(frame('text_delta', { turn_id: 't1', text: '你', seq: null }))
      onEvent(block('想好了', 1))
      onEvent(frame('text', { turn_id: 't1', text: '你好', seq: 2 }))

      expect(result.items.value.map((i) => i.kind)).toEqual(['user_message', 'thinking', 'text'])
      expect(result.items.value[1]).toMatchObject({ text: '想好了', streaming: false })
      expect(result.items.value[2]).toMatchObject({ text: '你好', streaming: false })
    })

    it('只有空白的 delta 和 thinking 不产生条目', async () => {
      const { result, onEvent } = await start()

      onEvent(delta('  \n'))
      onEvent(block('   ', 1))
      onEvent(block('', 2))

      expect(result.items.value.some((i) => i.kind === 'thinking')).toBe(false)
    })
  })

  it('turns 暴露挂载时加载的 turn 元数据', async () => {
    getSessionMock.mockResolvedValue(sessionDetail({ turns: [turnFixture('done')] }))

    const { result } = await setup('s1')

    expect(result.turns.value.get('t1')).toMatchObject({ id: 't1', status: 'done' })
    expect(result.turns.value.size).toBe(1)
  })

  it('刷新会话详情后 turns 包含新出现的 turn', async () => {
    getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turnFixture('running')] }))
    const { result } = await setup('s1')
    const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
    getSessionMock.mockResolvedValueOnce(
      sessionDetail({ turns: [turnFixture('done'), { ...turnFixture('running'), id: 't2' }] }),
    )

    onEvent(
      frame('snapshot', {
        turn_id: 't1',
        snapshot_id: 'snap1',
        reason: 'turn',
        created: true,
        seq: 3,
      }),
    )
    await flushAsync()

    expect([...result.turns.value.keys()].sort()).toEqual(['t1', 't2'])
    expect(result.turns.value.get('t1')?.status).toBe('done')
  })

  describe('turn 元数据与用户消息时间', () => {
    it('turn 结束（turn_status done）后重新拉取会话详情，turns 拿到最终的用量和时间', async () => {
      getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turnFixture('running')] }))
      const { result } = await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
      getSessionMock.mockResolvedValueOnce(
        sessionDetail({
          turns: [{ ...turnFixture('done'), usage: { input_tokens: 5, output_tokens: 7 } }],
        }),
      )

      onEvent(frame('turn_status', { turn_id: 't1', status: 'done', error: null, seq: null }))
      await flushAsync()

      expect(getSessionMock).toHaveBeenCalledTimes(2)
      expect(result.turns.value.get('t1')?.usage).toEqual({ input_tokens: 5, output_tokens: 7 })
    })

    it('运行中的 turn_status 不触发刷新', async () => {
      getSessionMock.mockResolvedValue(sessionDetail({ turns: [turnFixture('running')] }))
      await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      onEvent(frame('turn_status', { turn_id: 't1', status: 'running', error: null, seq: null }))
      await flushAsync()

      expect(getSessionMock).toHaveBeenCalledTimes(1)
    })

    it('乐观占位带发送时间，被真实 turn 认领后保留', async () => {
      getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
      const { result } = await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void

      result.addLocalUserMessage('你好')
      const placeholder = result.items.value[0]
      expect(placeholder).toMatchObject({ kind: 'user_message', turnId: 'local-0' })
      const at = (placeholder as { at?: string }).at
      expect(typeof at).toBe('string')
      expect(Number.isNaN(new Date(at!).getTime())).toBe(false)

      onEvent(frame('text', { turn_id: 't-real', text: '收到', seq: 1 }))

      expect(result.items.value[0]).toMatchObject({ kind: 'user_message', turnId: 't-real', at })
    })
  })

  describe('markTurnAccepted（发送接口返回 turn_id 后立刻标成排队中）', () => {
    async function start() {
      getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
      const { result } = await setup('s1')
      const onEvent = openStreamMock.mock.calls[0]![1].onEvent as (e: StreamEvent) => void
      return { result, onEvent }
    }
    const status = (turn: string, value: string) =>
      frame('turn_status', { turn_id: turn, status: value, error: null, seq: null })

    it('还没收到任何 turn_status 时，把这一轮标成 queued（瞬时事件可能被错过）', async () => {
      const { result } = await start()

      result.markTurnAccepted('t9', '你好')

      expect(result.turnStatus.value).toEqual({
        turnId: 't9',
        status: 'queued',
        error: null,
        neverStarted: false,
        userMessage: '你好',
      })
    })

    it('之后到达的 turn_status 照常覆盖', async () => {
      const { result, onEvent } = await start()
      result.markTurnAccepted('t9', '你好')

      onEvent(status('t9', 'running'))
      expect(result.turnStatus.value?.status).toBe('running')
      onEvent(status('t9', 'done'))
      expect(result.turnStatus.value?.status).toBe('done')
    })

    it('这一轮的 turn_status 已经先到时，不降级回 queued', async () => {
      const { result, onEvent } = await start()
      onEvent(status('t9', 'running'))

      result.markTurnAccepted('t9', '你好')

      expect(result.turnStatus.value?.status).toBe('running')
    })

    it('整轮都没收到瞬时事件（连接比发送晚）时，延迟核对会话详情，不会一直卡在排队中', async () => {
      vi.useFakeTimers()
      try {
        getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
        const { result } = await setup('s1')
        getSessionMock.mockResolvedValueOnce(sessionDetail({ turns: [turnFixture('done', 't9')] }))

        result.markTurnAccepted('t9', '你好')
        expect(result.turnStatus.value?.status).toBe('queued')
        await vi.advanceTimersByTimeAsync(1600)
        await flushAsync()

        expect(result.turnStatus.value).toMatchObject({ turnId: 't9', status: 'done' })
      } finally {
        vi.useRealTimers()
      }
    })

    it('延迟核对时这一轮已经结束就不再请求', async () => {
      vi.useFakeTimers()
      try {
        getSessionMock.mockResolvedValue(sessionDetail({ turns: [] }))
        const { onEvent, result } = await start()
        result.markTurnAccepted('t9', '你好')
        onEvent(status('t9', 'done'))
        await flushAsync()
        getSessionMock.mockClear()

        await vi.advanceTimersByTimeAsync(10_000)

        expect(getSessionMock).not.toHaveBeenCalled()
      } finally {
        vi.useRealTimers()
      }
    })

    it('上一轮已结束时，新一轮标成 queued', async () => {
      const { result, onEvent } = await start()
      onEvent(status('t1', 'done'))

      result.markTurnAccepted('t2', '再来')

      expect(result.turnStatus.value).toMatchObject({ turnId: 't2', status: 'queued' })
    })
  })
})
