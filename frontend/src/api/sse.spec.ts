import { afterEach, describe, expect, it, vi } from 'vitest'
import { openStream, SseFrameParser, type SseConnectionStatus } from '@/api/sse'
import type { StreamEvent } from '@/types/events'

describe('SseFrameParser', () => {
  it('解析单个 chunk 里的完整事件', () => {
    const parser = new SseFrameParser()
    const frames = parser.push('event: text\nid: 1\ndata: {"a":1}\n\n')
    expect(frames).toEqual([{ event: 'text', id: '1', data: '{"a":1}' }])
  })

  it('跨 chunk 边界断在一行中间也能正确拼出事件', () => {
    const parser = new SseFrameParser()
    expect(parser.push('event: te')).toEqual([])
    expect(parser.push('xt\nid: 1\ndata: {"a"')).toEqual([])
    const frames = parser.push(':1}\n\n')
    expect(frames).toEqual([{ event: 'text', id: '1', data: '{"a":1}' }])
  })

  it('跨 chunk 边界断在两个事件之间也能正确拆分', () => {
    const parser = new SseFrameParser()
    const first = parser.push('event: text\nid: 1\ndata: {"a":1}\n\nevent: text\nid: 2\n')
    expect(first).toEqual([{ event: 'text', id: '1', data: '{"a":1}' }])
    const second = parser.push('data: {"a":2}\n\n')
    expect(second).toEqual([{ event: 'text', id: '2', data: '{"a":2}' }])
  })

  it('多行 data 用换行拼接，不是覆盖', () => {
    const parser = new SseFrameParser()
    const frames = parser.push('event: text\ndata: line1\ndata: line2\n\n')
    expect(frames).toEqual([{ event: 'text', id: undefined, data: 'line1\nline2' }])
  })

  it('支持 CRLF 行结尾', () => {
    const parser = new SseFrameParser()
    const frames = parser.push('event: text\r\nid: 1\r\ndata: {"a":1}\r\n\r\n')
    expect(frames).toEqual([{ event: 'text', id: '1', data: '{"a":1}' }])
  })

  it('以冒号开头的注释行（sse-starlette 心跳 ping）被忽略', () => {
    const parser = new SseFrameParser()
    const frames = parser.push(': ping\n\nevent: text\ndata: {}\n\n')
    expect(frames).toEqual([{ event: 'text', id: undefined, data: '{}' }])
  })

  it('瞬时事件没有 id 字段', () => {
    const parser = new SseFrameParser()
    const frames = parser.push('event: text_delta\ndata: {"text":"hi"}\n\n')
    expect(frames[0]?.id).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// openStream：mock fetch，用可控的 ReadableStream 模拟后端 SSE 响应。
// ---------------------------------------------------------------------------

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
  return new Response(stream, { status })
}

function frame(type: string, payload: Record<string, unknown>, id?: string): string {
  const idLine = id !== undefined ? `id: ${id}\n` : ''
  return `event: ${type}\n${idLine}data: ${JSON.stringify(payload)}\n\n`
}

describe('openStream', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('转发流里的每个事件', async () => {
    const events: StreamEvent[] = []
    const body = frame('text', { turn_id: 't1', text: 'hi', seq: 1 }, '1')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(sseResponse([body])).mockImplementation(() => Promise.resolve(sseResponse([]))),
    )
    const controller = new AbortController()

    openStream('/api/sessions/s1/stream', {
      onEvent: (e) => events.push(e),
      signal: controller.signal,
      reconnectDelaysMs: [0],
    })

    await vi.waitFor(() => expect(events).toHaveLength(1))
    expect(events[0]).toEqual({ type: 'text', payload: { turn_id: 't1', text: 'hi', seq: 1 } })
    controller.abort()
  })

  it('重连时带上最新收到的 seq 作为 after_seq', async () => {
    const events: StreamEvent[] = []
    const firstBody = frame('text', { turn_id: 't1', text: 'a', seq: 5 }, '5')
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sseResponse([firstBody])) // 第一次连接，流结束（模拟断线）
      .mockImplementation(() => Promise.resolve(sseResponse([]))) // 之后的重连不再产出新事件
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    openStream('/api/sessions/s1/stream', {
      afterSeq: 0,
      onEvent: (e) => events.push(e),
      signal: controller.signal,
      reconnectDelaysMs: [0, 0, 0],
    })

    await vi.waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2))
    const secondUrl = String(fetchMock.mock.calls[1]![0])
    expect(secondUrl).toContain('after_seq=5')
    controller.abort()
  })

  it('重连交界处重复的持久事件（seq 未超过 after_seq）被去重', async () => {
    const events: StreamEvent[] = []
    const firstBody = frame('text', { turn_id: 't1', text: 'a', seq: 5 }, '5')
    const dupBody = frame('text', { turn_id: 't1', text: 'a-dup', seq: 5 }, '5')
    const newBody = frame('text', { turn_id: 't1', text: 'b', seq: 6 }, '6')
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sseResponse([firstBody]))
      .mockResolvedValueOnce(sseResponse([dupBody, newBody]))
      .mockImplementation(() => Promise.resolve(sseResponse([])))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    openStream('/api/sessions/s1/stream', {
      onEvent: (e) => events.push(e),
      signal: controller.signal,
      reconnectDelaysMs: [0, 0, 0],
    })

    await vi.waitFor(() => expect(events).toHaveLength(2))
    expect(events.map((e) => e.payload.seq)).toEqual([5, 6])
    controller.abort()
  })

  it('4xx 响应报告失败且不重连', async () => {
    const statuses: SseConnectionStatus[] = []
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response('{"detail":"非法的 after_seq"}', { status: 400 }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    openStream('/api/sessions/s1/stream', {
      onEvent: () => {},
      onStatus: (s) => statuses.push(s),
      signal: controller.signal,
      reconnectDelaysMs: [0],
    })

    await vi.waitFor(() =>
      expect(statuses.some((s) => s.kind === 'failed')).toBe(true),
    )
    // 给可能的（错误）重连留一点时间，确认确实没有发生。
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    controller.abort()
  })

  it('abort 后不再重连、不再产出事件', async () => {
    const events: StreamEvent[] = []
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(sseResponse([])))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    openStream('/api/sessions/s1/stream', {
      onEvent: (e) => events.push(e),
      signal: controller.signal,
      reconnectDelaysMs: [0],
    })

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    controller.abort()
    const callsAtAbort = fetchMock.mock.calls.length
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(callsAtAbort + 1)
  })
})
