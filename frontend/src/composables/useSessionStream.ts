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
 * T12 遗留的已知限制在 T13 里解决：本次挂载之后才发送的消息，`turn_id`
 * 不在挂载时拉到的 `turns` 列表里，`ensureUserMessage` 原本拿不到文本。
 * 现在会话面板发消息时改调 `addLocalUserMessage(text)` 乐观插入一条占位
 * （`turnId` 是本地生成的 `local-<n>`），`ensureUserMessage` 见到任意
 * 新 `turn_id` 的第一个事件时优先按 FIFO 顺序认领最早的一条待处理占位、
 * 原地把 `turnId` 换成真实值，而不是去 `knownTurns` 查（查不到就只能插空
 * 文本）。`sessionId` 切换时占位队列会清空，避免旧会话遗留的占位被新会话
 * 的 turn 误认领。发送请求本身失败（409/网络错误等，从没真正创建 turn）
 * 时，调用方要用 `addLocalUserMessage` 返回的 `turnId` 调
 * `removeLocalUserMessage` 撤回占位（T13 审查修复）——否则这条占位会一直
 * 占着 `pendingLocalMessages` 队首，下一条真正发出去的消息的真实 turn 会
 * 被 FIFO 错误配对到这条"其实没发出去"的占位上。
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
  ToolResultImage,
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
  /**
   * `images` 透传自 `ToolResultPayload.images`：M1 后端只持久化
   * `media_type`（审查裁定，见计划「已知限制」），不存图片内容本身，所以
   * 这里永远拿不到可渲染的图片数据、只能数出有几张——`SessionTimelineItem`
   * 用它渲染一句"含 N 张图片（M1 未存图片内容，不可预览）"的文字占位，
   * 不是真的缩略图。M2 落地 `render_preview` 关键帧时如果需要真缩略图，
   * 要先在后端补图片内容的持久化。
   */
  result?: { text: string; isError: boolean; truncated: boolean; images: ToolResultImage[] }
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
  /**
   * 乐观插入一条用户消息（任务简报 T13，控制者裁定 3；解决上面文档「已知
   * 限制」）：会话面板发消息时手头就有文本，不用等 SSE 回放出真实
   * `turn_id`。占位项先用 `local-<n>` 当 `turnId` 插入 `items`；等这个
   * turn 的第一个事件到达、`ensureUserMessage` 按 FIFO 顺序认领一个待
   * 处理的占位时，原地把占位的 `turnId` 换成真实值，不会同时存在"占位 +
   * 空文本"两条。返回这条占位的 `turnId`（`local-<n>`），发送失败时传给
   * `removeLocalUserMessage` 撤回。
   */
  addLocalUserMessage: (text: string) => string
  /**
   * 撤回一条还没被真实 turn 认领的乐观占位（T13 审查修复：发送失败——
   * 409/网络错误等——如果不撤回，占位会一直留在 `items` 里、并且还占着
   * `pendingLocalMessages` 队首，导致下一次真正发出去的消息在 FIFO 里排到
   * 它后面，被下一个真实 turn 的事件错误配对到这条"其实没发出去"的占位
   * 上。`turnId` 不在队列里（已经被认领，或者本来就传错）时是安全的
   * no-op，不做任何事。
   */
  removeLocalUserMessage: (placeholderId: string) => void
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
  // 乐观插入、还没被真实 turn 认领的占位（FIFO：先发送的消息先配对）。
  let pendingLocalMessages: { placeholderId: string; text: string }[] = []
  let localMessageCounter = 0

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
    pendingLocalMessages = [] // 上一个会话遗留的占位不能被下一个会话的 turn 认领。
    projectId = null
  }

  function addLocalUserMessage(text: string): string {
    const placeholderId = `local-${localMessageCounter}`
    localMessageCounter += 1
    pendingLocalMessages.push({ placeholderId, text })
    items.value.push({ kind: 'user_message', turnId: placeholderId, text })
    return placeholderId
  }

  function removeLocalUserMessage(placeholderId: string): void {
    const pendingIdx = pendingLocalMessages.findIndex((p) => p.placeholderId === placeholderId)
    if (pendingIdx !== -1) pendingLocalMessages.splice(pendingIdx, 1)

    const itemIdx = items.value.findIndex(
      (item) => item.kind === 'user_message' && item.turnId === placeholderId,
    )
    if (itemIdx !== -1) items.value.splice(itemIdx, 1)
  }

  function ensureUserMessage(turnId: string): void {
    if (userMessageInserted.has(turnId)) return
    userMessageInserted.add(turnId)

    const pending = pendingLocalMessages.shift()
    if (pending) {
      const idx = items.value.findIndex(
        (item) => item.kind === 'user_message' && item.turnId === pending.placeholderId,
      )
      if (idx !== -1) {
        items.value[idx] = { kind: 'user_message', turnId, text: pending.text }
        return
      }
    }

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
            images: payload.images,
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

  return { items, turnStatus, connectionStatus, addLocalUserMessage, removeLocalUserMessage }
}
