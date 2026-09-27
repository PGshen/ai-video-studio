/**
 * 会话的实时状态：把 SSE 事件合并成一条可渲染的时间线（任务简报 T12，
 * 控制者裁定 4；评审关注点 2）。
 *
 * ## 历史 + 实时如何拼起来
 *
 * `_stream_events`（后端）在新连接建立时先回放 `seq > after_seq` 的**持久**
 * 事件（`text`/`tool_call`/`tool_result`/`notice`/`error`/`snapshot`），
 * 这些回放是会话级的（不分 turn），所以从 `after_seq=0` 打开一次连接就能
 * 拿到这个会话历史上全部 turn 的完整事件体，按 `turn_id` 字段就能归到各自
 * 的 turn 下——不需要额外改后端、也不需要按 turn 再单独拉一次。
 *
 * 但 `turn_status` 和用户发的消息文本**不在**这份回放里：
 * - `turn_status` 是瞬时事件（没有 `seq`），只在事件当时正在监听总线的
 *   客户端能收到，重连/首次挂载都补不回来。
 * - 用户消息文本从来不是一种 SSE 事件（`TurnRunner` 不发布它），只存在于
 *   `turns` 表的 `user_message` 字段。
 *
 * 所以初始状态用 `GET /sessions/{id}`（一次性调用，不经 TanStack Query，
 * 保持这个 composable 自成一体、方便直接测试）拿到的 `turns` 列表补齐这两
 * 样：每个 turn 的 `user_message` 用来在时间线里插一条"用户消息"，
 * `status` 用作挂载时的初始 turn 状态；再打开 SSE（`afterSeq: 0`）接收
 * 回放和之后的实时事件。一条用户消息在时间线里的位置 = 它所属 turn 的
 * 第一个事件到达之前（`ensureUserMessage`：见到某个 `turn_id` 的第一条
 * 事件时，如果这个 turn 还没插入过用户消息，先插）。
 *
 * 已知限制（记入计划「决策记录」/「意外与发现」，不在本任务内解决）：如果
 * 消息是在本次挂载**之后**才发送的（`turn_id` 不在挂载时拉到的 `turns`
 * 列表里），`ensureUserMessage` 拿不到这个 turn 的 `user_message`
 * 文本，会插入一条空文本的占位——真实文本在调用 `sendMessage` 的那一层
 * （T13 的会话面板）手头就有，应该由那一层在乐观更新时直接补上，而不是
 * 这个通用 composable 去猜。
 */

import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { getSession, sessionStreamUrl } from '@/api/endpoints'
import { openStream, type SseConnectionStatus } from '@/api/sse'
import { invalidateWorkspace } from '@/composables/queries'
import type { TurnOut } from '@/types/api'
import type {
  ErrorEventPayload,
  NoticePayload,
  SnapshotEventPayload,
  StreamEvent,
  TextDeltaPayload,
  TextPayload,
  ToolCallPayload,
  ToolResultPayload,
  TurnStatusPayload,
} from '@/types/events'

export interface UserMessageItem {
  kind: 'user_message'
  turnId: string
  text: string
}

export interface TextItem {
  kind: 'text'
  turnId: string
  text: string
  /** 还在通过 `text_delta` 累积、没有收到最终 `text` 事件替换掉。 */
  streaming: boolean
}

export interface ToolCallItem {
  kind: 'tool_call'
  turnId: string
  callId: string
  name: string
  args: Record<string, unknown>
  result?: { text: string; isError: boolean; truncated: boolean }
}

export interface NoticeItem {
  kind: 'notice'
  turnId: string
  noticeKind: string
  message?: string
  paths?: string[]
}

export interface ErrorItem {
  kind: 'error'
  turnId: string
  message: string
}

export interface SnapshotItem {
  kind: 'snapshot'
  turnId: string
  snapshotId: string
  reason: string
}

export type TimelineItem =
  | UserMessageItem
  | TextItem
  | ToolCallItem
  | NoticeItem
  | ErrorItem
  | SnapshotItem

export interface TurnStatusState {
  turnId: string
  status: string
  error: string | null
}

export interface UseSessionStreamResult {
  items: Ref<TimelineItem[]>
  turnStatus: Ref<TurnStatusState | null>
  connectionStatus: Ref<SseConnectionStatus | null>
}

function findLastStreamingTextIndex(items: TimelineItem[], turnId: string): number {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const item = items[i]!
    if (item.turnId !== turnId) continue
    if (item.kind === 'text' && item.streaming) return i
    if (item.kind !== 'user_message') return -1 // 这个 turn 后来的事件已经把这段文本"接住"了。
  }
  return -1
}

export function useSessionStream(sessionId: Ref<string | null>): UseSessionStreamResult {
  const queryClient = useQueryClient()
  const items = ref<TimelineItem[]>([]) as Ref<TimelineItem[]>
  const turnStatus = ref<TurnStatusState | null>(null) as Ref<TurnStatusState | null>
  const connectionStatus = ref<SseConnectionStatus | null>(null) as Ref<SseConnectionStatus | null>

  let controller: AbortController | null = null
  let projectId: string | null = null
  const knownTurns = new Map<string, TurnOut>()
  const userMessageInserted = new Set<string>()
  const toolCallIndex = new Map<string, number>()

  // 审查发现的竞态（`sessionId` 在上一次 `watch` 回调还卡在 `await
  // loadHistory` 时又变了一次）：`generation` 每次回调开始时自增一，回调
  // 自己的编号存进 `myGeneration`；`await` 之后、以及每个 SSE 回调触发时都
  // 检查编号是不是还等于最新的 `generation`——不等就说明这次回调已经过期
  // （有更新的 `sessionId` 变化发生过），直接丢弃这次的结果，不写共享状态、
  // 不打开连接。只有"当前最新"的那次回调有机会调用 `connect()`，所以不会
  // 出现两条流同时往同一份 `items`/`turnStatus` 写数据的情况；`disconnect()`
  // 仍然在每次回调开始时同步调用，负责立刻掐断"上一个已经连上的"流（它不是
  // 过期回调，是真的要被替换掉的现役连接）。
  let generation = 0

  function reset(): void {
    items.value = []
    turnStatus.value = null
    connectionStatus.value = null
    knownTurns.clear()
    userMessageInserted.clear()
    toolCallIndex.clear()
    projectId = null
  }

  function ensureUserMessage(turnId: string): void {
    if (userMessageInserted.has(turnId)) return
    userMessageInserted.add(turnId)
    const turn = knownTurns.get(turnId)
    items.value.push({ kind: 'user_message', turnId, text: turn?.user_message ?? '' })
  }

  function handleEvent(event: StreamEvent): void {
    const turnId = event.payload.turn_id
    if (turnId) ensureUserMessage(turnId)

    switch (event.type) {
      case 'text_delta': {
        const payload = event.payload as TextDeltaPayload
        const last = items.value.at(-1)
        if (last && last.kind === 'text' && last.turnId === payload.turn_id && last.streaming) {
          last.text += payload.text
        } else {
          items.value.push({
            kind: 'text',
            turnId: payload.turn_id,
            text: payload.text,
            streaming: true,
          })
        }
        break
      }
      case 'text': {
        const payload = event.payload as TextPayload
        const idx = findLastStreamingTextIndex(items.value, payload.turn_id)
        const resolved: TextItem = {
          kind: 'text',
          turnId: payload.turn_id,
          text: payload.text,
          streaming: false,
        }
        if (idx !== -1) {
          items.value[idx] = resolved
        } else {
          items.value.push(resolved)
        }
        break
      }
      case 'tool_call': {
        const payload = event.payload as ToolCallPayload
        toolCallIndex.set(payload.call_id, items.value.length)
        items.value.push({
          kind: 'tool_call',
          turnId: payload.turn_id,
          callId: payload.call_id,
          name: payload.name,
          args: payload.args,
        })
        break
      }
      case 'tool_result': {
        const payload = event.payload as ToolResultPayload
        const idx = toolCallIndex.get(payload.call_id)
        const call = idx !== undefined ? items.value[idx] : undefined
        if (call && call.kind === 'tool_call') {
          call.result = {
            text: payload.text,
            isError: payload.is_error,
            truncated: payload.truncated,
          }
        }
        break
      }
      case 'notice': {
        const payload = event.payload as NoticePayload
        items.value.push({
          kind: 'notice',
          turnId: payload.turn_id,
          noticeKind: payload.kind,
          message: payload.message,
          paths: payload.paths,
        })
        break
      }
      case 'error': {
        const payload = event.payload as ErrorEventPayload
        items.value.push({ kind: 'error', turnId: payload.turn_id, message: payload.message })
        break
      }
      case 'snapshot': {
        const payload = event.payload as SnapshotEventPayload
        items.value.push({
          kind: 'snapshot',
          turnId: payload.turn_id,
          snapshotId: payload.snapshot_id,
          reason: payload.reason,
        })
        if (projectId) void invalidateWorkspace(queryClient, projectId)
        break
      }
      case 'workspace_changed': {
        if (projectId) void invalidateWorkspace(queryClient, projectId)
        break
      }
      case 'turn_status': {
        const payload = event.payload as TurnStatusPayload
        turnStatus.value = { turnId: payload.turn_id, status: payload.status, error: payload.error }
        break
      }
    }
  }

  function applyHistory(detail: Awaited<ReturnType<typeof getSession>>): void {
    projectId = detail.project_id
    for (const turn of detail.turns) {
      knownTurns.set(turn.id, turn)
    }
    const last = detail.turns.at(-1)
    if (last) {
      turnStatus.value = { turnId: last.id, status: last.status, error: last.error }
    }
  }

  function connect(id: string, myGeneration: number): void {
    const myController = new AbortController()
    controller = myController
    openStream(sessionStreamUrl(id), {
      afterSeq: 0,
      onEvent: (event) => {
        if (myGeneration !== generation) return // 过期连接的事件，丢弃。
        handleEvent(event)
      },
      onStatus: (status) => {
        if (myGeneration !== generation) return
        connectionStatus.value = status
      },
      signal: myController.signal,
    })
  }

  function disconnect(): void {
    controller?.abort()
    controller = null
  }

  watch(
    sessionId,
    async (id) => {
      generation += 1
      const myGeneration = generation
      disconnect() // 掐断上一个真正连上的流（不是过期回调，是要被替换的现役连接）。
      reset()
      if (id === null) return
      const detail = await getSession(id)
      if (myGeneration !== generation) return // 等待期间又换了一次 sessionId，这次结果作废。
      applyHistory(detail)
      connect(id, myGeneration)
    },
    { immediate: true },
  )

  onScopeDispose(() => {
    generation += 1 // 让任何还没落地的 loadHistory/connect 在恢复执行时发现自己已经过期。
    disconnect()
  })

  return { items, turnStatus, connectionStatus }
}
