/**
 * SSE 线上事件的 payload 类型（任务简报 T12），对应
 * `backend/src/studio/api/sessions.py` 的 `WIRE_EVENT_TYPES` 和
 * `backend/src/studio/agent/runner.py` 里各事件的实际 payload 形状。
 *
 * 每条 SSE 消息的 `data` JSON 都是 `{...payload, seq}`：持久事件
 * （`text`/`tool_call`/`tool_result`/`notice`/`error`/`snapshot`）的 `seq`
 * 是会话内单调递增的整数，同时出现在 SSE 帧的 `id` 字段；瞬时事件
 * （`text_delta`/`workspace_changed`/`turn_status`）的 `seq` 恒为 `null`，
 * SSE 帧没有 `id` 字段。所有持久/瞬时事件的 payload 都带 `turn_id`
 * （见 `TurnRunner._persist`/`_publish`），可用它把事件和 `GET
 * /sessions/{id}` 返回的 turn 列表关联起来。
 */

export type WireEventType =
  | 'text_delta'
  | 'text'
  | 'thinking_delta'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'snapshot'
  | 'suggestion'
  | 'notice'
  | 'error'
  | 'workspace_changed'
  | 'turn_status'

export interface TextDeltaPayload {
  turn_id: string
  text: string
  seq: null
}

export interface TextPayload {
  turn_id: string
  text: string
  seq: number
}

export interface ThinkingDeltaPayload {
  turn_id: string
  text: string
  seq: null
}

export interface ThinkingPayload {
  turn_id: string
  text: string
  seq: number
}

export interface ToolCallPayload {
  turn_id: string
  call_id: string
  name: string
  args: Record<string, unknown>
  seq: number
}

export interface ToolResultImage {
  media_type: string
  /** `BlobStore` 的内容寻址 key（TD-21）：配 `blobUrl(projectId, sha256)` 取字节内容。 */
  sha256: string
}

export interface ToolResultPayload {
  turn_id: string
  call_id: string
  text: string
  truncated: boolean
  is_error: boolean
  images: ToolResultImage[]
  seq: number
}

export interface SnapshotEventPayload {
  turn_id: string
  snapshot_id: string
  reason: string
  created: boolean
  seq: number
}

/** 下游 agent 提了一条回退建议（M5 T9）；状态以 `GET /suggestions` 为准，事件里的 `status` 只是当时的值。 */
export interface SuggestionEventPayload {
  turn_id: string
  suggestion_id: string
  from_stage: string
  to_stage: string
  content: string
  status: string
  seq: number
}

/** `kind` 已知取值：`cost_unpriced`、`cost_carryover`、`budget_exceeded`、`guard_restored`。 */
export interface NoticePayload {
  turn_id: string
  kind: string
  message?: string
  budget?: string
  paths?: string[]
  seq: number
}

export interface ErrorEventPayload {
  turn_id: string
  message: string
  seq: number
}

export interface WorkspaceChangedPayload {
  turn_id: string
  paths: string[]
  seq: null
}

export interface TurnStatusPayload {
  turn_id: string
  status: string
  error: string | null
  seq: null
}

export interface WireEventMap {
  text_delta: TextDeltaPayload
  text: TextPayload
  thinking_delta: ThinkingDeltaPayload
  thinking: ThinkingPayload
  tool_call: ToolCallPayload
  tool_result: ToolResultPayload
  snapshot: SnapshotEventPayload
  suggestion: SuggestionEventPayload
  notice: NoticePayload
  error: ErrorEventPayload
  workspace_changed: WorkspaceChangedPayload
  turn_status: TurnStatusPayload
}

/** `sse.ts` 解析出的一条事件：线上事件名 + 原始 JSON payload。 */
export interface StreamEvent<T extends WireEventType = WireEventType> {
  type: T
  payload: WireEventMap[T]
}
