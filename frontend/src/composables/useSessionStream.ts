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
 *
 * `turn_status` 不回放带来的问题（M1 最终审查 I3）：断线期间一轮结束，重连
 * 后前端收不到那条 `turn_status`，会一直显示"运行中"。所以连接从
 * `reconnecting` 回到 `open` 时重新 `GET /sessions/{id}` 覆盖 `turnStatus`；
 * 当前运行中 turn 的 `snapshot` 事件（一轮收尾时落库、会被回放）到达时也
 * 刷新一次。刷新响应到达前如果已经收到更新的 `turn_status`，响应作废
 * （`statusVersion`），同样受 `generation` 防竞态保护。
 */

import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { getSession, sessionStreamUrl } from '@/api/endpoints'
import { openStream, type SseConnectionStatus } from '@/api/sse'
import { isIdeaWriteTool } from '@/composables/ideaEvents'
import { invalidateWorkspace, queryKeys } from '@/composables/queries'
import type { TurnOut } from '@/types/api'
import type {
  ErrorEventPayload,
  NoticePayload,
  SnapshotEventPayload,
  StreamEvent,
  SuggestionEventPayload,
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
   * `images` 透传自 `ToolResultPayload.images`：每张图带 `sha256`（TD-21
   * 修复后），`SessionTimelineItem` 据此拼 `blobUrl(projectId, sha256)`
   * 渲染真缩略图，不再只是"含 N 张图片"的文字占位。
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

/** 下游 agent 提的回退建议（M5 T9）；处理状态不放在条目里，由卡片按 `suggestionId` 查最新状态。 */
export interface SuggestionItem {
  kind: 'suggestion'
  turnId: string
  suggestionId: string
  fromStage: string
  toStage: string
  content: string
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
  /** 后端本次是否新建了快照；`false` 表示内容没变、沿用已有快照（M4）。 */
  created: boolean
}

export type TimelineItem =
  | UserMessageItem
  | TextItem
  | ToolCallItem
  | NoticeItem
  | SuggestionItem
  | ErrorItem
  | SnapshotItem

export interface TurnStatusState {
  turnId: string
  status: string
  error: string | null
  /** 重启时还在排队、从未开始运行（TD-19）：[继续] 重发 `userMessage`。只有从会话详情来的状态才准确。 */
  neverStarted: boolean
  userMessage: string | null
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
  // 每收到一条实时 `turn_status` 自增；刷新请求发出后它变了，说明响应已经过时。
  let statusVersion = 0
  let lastConnectionKind: SseConnectionStatus['kind'] | null = null

  function reset(): void {
    items.value = []
    turnStatus.value = null
    connectionStatus.value = null
    knownTurns.clear()
    userMessageInserted.clear()
    toolCallIndex.clear()
    pendingLocalMessages = [] // 上一个会话遗留的占位不能被下一个会话的 turn 认领。
    projectId = null
    lastConnectionKind = null
  }

  function isBusy(status: string | undefined): boolean {
    return status === 'queued' || status === 'running'
  }

  function statusOf(turn: TurnOut): TurnStatusState {
    return {
      turnId: turn.id,
      status: turn.status,
      error: turn.error,
      neverStarted: turn.never_started,
      userMessage: turn.user_message,
    }
  }

  /** 重新拉取会话，用最近一个 turn 的状态覆盖 `turnStatus`（I3）。 */
  async function refreshTurnStatus(id: string, myGeneration: number): Promise<void> {
    const versionAtRequest = statusVersion
    let detail: Awaited<ReturnType<typeof getSession>>
    try {
      detail = await getSession(id)
    } catch {
      return // 下一次重连或 snapshot 事件会再试。
    }
    if (myGeneration !== generation || versionAtRequest !== statusVersion) return
    for (const turn of detail.turns) knownTurns.set(turn.id, turn)
    const last = detail.turns.at(-1)
    if (last) turnStatus.value = statusOf(last)
    if (projectId) void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
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

  function handleEvent(event: StreamEvent, id: string, myGeneration: number): void {
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
          // 头脑风暴 agent 建/改了卡片：选题池不用手动刷新（M4 T10）。
          if (isIdeaWriteTool(call.name)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.ideasAll() })
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
      case 'suggestion': {
        const payload = event.payload as SuggestionEventPayload
        items.value.push({
          kind: 'suggestion',
          turnId: payload.turn_id,
          suggestionId: payload.suggestion_id,
          fromStage: payload.from_stage,
          toStage: payload.to_stage,
          content: payload.content,
        })
        // 阶段导航的角标和建议列表要跟上（所有项目的建议查询共用前缀，见 `queryKeys.suggestionsAll`）。
        void queryClient.invalidateQueries({ queryKey: queryKeys.suggestionsAll() })
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
          created: payload.created,
        })
        if (projectId) void invalidateWorkspace(queryClient, projectId)
        const current = turnStatus.value
        if (current && current.turnId === payload.turn_id && isBusy(current.status)) {
          void refreshTurnStatus(id, myGeneration)
        }
        break
      }
      case 'workspace_changed': {
        if (projectId) void invalidateWorkspace(queryClient, projectId)
        break
      }
      case 'turn_status': {
        const payload = event.payload as TurnStatusPayload
        statusVersion += 1
        const known = knownTurns.get(payload.turn_id)
        turnStatus.value = {
          turnId: payload.turn_id,
          status: payload.status,
          error: payload.error,
          neverStarted: false,
          userMessage: known?.user_message ?? null,
        }
        // `never_started` is only computed by the backend's session detail (TD-19).
        if (payload.status === 'interrupted') void refreshTurnStatus(id, myGeneration)
        // 项目详情（`ProjectDetailOut.busy`）失效：当前会话的 turn 一
        // 开始/结束，画布的只读判断（T14 审查修复：`combineBusy`）应该
        // 立刻反映，不等 `useProjectQuery` 的 3 秒轮询周期。只有
        // `projectId`（挂载历史时从 `GET /sessions/{id}` 拿到）已知时
        // 才失效——理论上 `turn_status` 必然晚于 `applyHistory`。
        if (projectId) void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
        // TD-33: a finished turn may have called validate_scenes/render_preview;
        // the scene-checks read model can only change when a turn ends.
        if (projectId) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.sceneChecksAll(projectId) })
        } else if (!isBusy(payload.status)) {
          // 无项目会话（头脑风暴）一轮结束：卡片可能变了（M4 T10）。
          void queryClient.invalidateQueries({ queryKey: queryKeys.ideasAll() })
        }
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
      turnStatus.value = statusOf(last)
      // A turn that never started has no events, so nothing would ever show its message;
      // show it so the user sees what [重新发送] will send (TD-19).
      if (last.never_started) ensureUserMessage(last.id)
    }
  }

  function connect(id: string, myGeneration: number): void {
    const myController = new AbortController()
    controller = myController
    openStream(sessionStreamUrl(id), {
      afterSeq: 0,
      onEvent: (event) => {
        if (myGeneration !== generation) return // 过期连接的事件，丢弃。
        handleEvent(event, id, myGeneration)
      },
      onStatus: (status) => {
        if (myGeneration !== generation) return
        const previous = lastConnectionKind
        lastConnectionKind = status.kind
        connectionStatus.value = status
        if (status.kind === 'open' && previous === 'reconnecting') {
          void refreshTurnStatus(id, myGeneration)
        }
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
