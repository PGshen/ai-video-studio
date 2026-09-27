/**
 * 基于 `fetch` + `ReadableStream` 的 SSE 客户端（任务简报 T12，控制者裁定
 * 3；评审关注点 2）。浏览器原生 `EventSource` 不能设置请求头也不能控制
 * 重连时携带的 `after_seq`，所以自己解析（`docs/references/frontend-stack.md`
 * 已记录这个结论）。
 *
 * 帧解析（`SseFrameParser`）遵循 SSE 规范的子集，够用即可：
 * - 按 `\n` 切行，`\r\n` 也支持（先切 `\n` 再去掉行尾的 `\r`）。
 * - `data:` 可以出现多次，多行 `data` 用 `\n` 拼接（不是覆盖）。
 * - 以 `:` 开头的行是注释（`sse-starlette` 的心跳 ping），忽略。
 * - 空行表示一条事件结束（dispatch）。
 * - 状态在多次 `push` 之间保留，能正确处理跨 chunk 边界断开的行/事件。
 *
 * 续传与去重（评审关注点 2）：`after_seq` 只在持久事件（payload 里
 * `seq` 不是 `null`）到达时推进；网络错误/流结束且未主动 abort 时，指数
 * 退避（1s→2s→4s→8s→10s，封顶）后用最新的 `after_seq` 重新连接；重连后
 * 服务端会重放 `seq > after_seq` 的事件，交界处如果服务端仍然多发了一条
 * 已经见过的持久事件（`seq <= after_seq`），客户端这里也会再去重一次。
 * 4xx（比如非法的 `after_seq`）不重连，直接报告。
 */

import type { StreamEvent, WireEventType } from '@/types/events'

interface SseFrame {
  id?: string
  event?: string
  data: string
}

/** 增量解析 SSE 字节流；每次 `push` 传入新到达的文本，返回本次凑齐的完整事件。 */
export class SseFrameParser {
  private buffer = ''
  private currentEvent: string | undefined
  private currentId: string | undefined
  private currentData: string[] = []
  private hasContent = false

  push(chunk: string): SseFrame[] {
    this.buffer += chunk
    const frames: SseFrame[] = []
    let newlineIndex: number
    while ((newlineIndex = this.buffer.indexOf('\n')) !== -1) {
      let line = this.buffer.slice(0, newlineIndex)
      this.buffer = this.buffer.slice(newlineIndex + 1)
      if (line.endsWith('\r')) {
        line = line.slice(0, -1)
      }

      if (line === '') {
        if (this.hasContent) {
          frames.push({
            id: this.currentId,
            event: this.currentEvent,
            data: this.currentData.join('\n'),
          })
        }
        this.currentEvent = undefined
        this.currentId = undefined
        this.currentData = []
        this.hasContent = false
        continue
      }

      if (line.startsWith(':')) {
        continue
      }

      this.hasContent = true
      const colonIndex = line.indexOf(':')
      const field = colonIndex === -1 ? line : line.slice(0, colonIndex)
      let value = colonIndex === -1 ? '' : line.slice(colonIndex + 1)
      if (value.startsWith(' ')) {
        value = value.slice(1)
      }

      if (field === 'data') {
        this.currentData.push(value)
      } else if (field === 'event') {
        this.currentEvent = value
      } else if (field === 'id') {
        this.currentId = value
      }
      // 其它字段（如 `retry`）本客户端不使用，忽略。
    }
    return frames
  }
}

export type SseConnectionStatus =
  | { kind: 'open' }
  | { kind: 'reconnecting'; delayMs: number; reason: string }
  | { kind: 'failed'; status: number; detail: unknown }

export interface OpenStreamOptions {
  /** 从哪个 seq 之后开始（含重连）；省略视为 0（从头回放）。 */
  afterSeq?: number
  onEvent: (event: StreamEvent) => void
  onStatus?: (status: SseConnectionStatus) => void
  signal?: AbortSignal
  /** 重连退避表（毫秒），可测试性注入；默认 1s→2s→4s→8s→10s（封顶）。 */
  reconnectDelaysMs?: number[]
}

const DEFAULT_RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 10000]

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  // 即使 `ms` 是 0 也要真正走一次宏任务（`setTimeout`），不能直接
  // `Promise.resolve()`：否则连续重连（比如 mock 测试里每次都立刻失败）会
  // 变成纯微任务的忙循环，饿死事件循环里的宏任务（定时器），
  // `signal` 的 abort 回调本身能同步触发，但依赖 abort 的测试代码
  // （比如轮询断言）用的定时器永远得不到执行机会。
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
  })
}

function withAfterSeq(url: string, afterSeq: number): string {
  const parsed = new URL(url, window.location.origin)
  parsed.searchParams.set('after_seq', String(afterSeq))
  return `${parsed.pathname}${parsed.search}`
}

async function readErrorDetail(response: Response): Promise<unknown> {
  try {
    const text = await response.text()
    if (!text) return null
    try {
      const body = JSON.parse(text) as { detail?: unknown }
      return body.detail ?? body
    } catch {
      return text
    }
  } catch {
    return null
  }
}

/**
 * 打开一条会话 SSE 流；断线（网络错误、流结束）后自动重连，直到
 * `signal` 被 abort 或收到 4xx。不返回值——所有产出都通过 `onEvent`/
 * `onStatus` 回调；调用方通过传入的 `AbortController.signal` 控制生命周期。
 */
export function openStream(url: string, options: OpenStreamOptions): void {
  const { onEvent, onStatus, signal } = options
  const delays = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS
  let lastSeq = options.afterSeq ?? 0
  let attempt = 0

  function processFrame(frame: SseFrame): void {
    if (frame.event === undefined) return
    let payload: Record<string, unknown>
    try {
      payload = frame.data ? (JSON.parse(frame.data) as Record<string, unknown>) : {}
    } catch {
      return // 畸形 data，丢弃这一条而不是让整条流崩溃。
    }
    const seq = payload.seq
    if (typeof seq === 'number') {
      if (seq <= lastSeq) return // 重放/重连交界处的重复持久事件。
      lastSeq = seq
    }
    onEvent({ type: frame.event as WireEventType, payload } as StreamEvent)
  }

  async function backoff(reason: string): Promise<void> {
    const delayMs = delays[Math.min(attempt, delays.length - 1)]
    attempt += 1
    onStatus?.({ kind: 'reconnecting', delayMs, reason })
    await sleep(delayMs, signal)
  }

  async function run(): Promise<void> {
    while (!signal?.aborted) {
      let response: Response
      try {
        response = await fetch(withAfterSeq(url, lastSeq), {
          signal,
          headers: { Accept: 'text/event-stream' },
        })
      } catch (err) {
        if (signal?.aborted || isAbortError(err)) return
        await backoff(err instanceof Error ? err.message : '网络错误')
        continue
      }

      if (!response.ok) {
        const detail = await readErrorDetail(response)
        onStatus?.({ kind: 'failed', status: response.status, detail })
        if (response.status >= 400 && response.status < 500) {
          return // 评审关注点 2：4xx（如非法 after_seq）不重连。
        }
        await backoff(`HTTP ${response.status}`)
        continue
      }

      attempt = 0
      onStatus?.({ kind: 'open' })

      const body = response.body
      if (body === null) {
        await backoff('响应没有 body')
        continue
      }

      const reader = body.getReader()
      const decoder = new TextDecoder()
      const parser = new SseFrameParser()
      let streamError: unknown = null
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          const text = decoder.decode(value, { stream: true })
          for (const frame of parser.push(text)) {
            processFrame(frame)
          }
        }
      } catch (err) {
        streamError = err
      }

      if (signal?.aborted || isAbortError(streamError)) return
      await backoff(streamError instanceof Error ? streamError.message : '连接中断')
    }
  }

  void run()
}
