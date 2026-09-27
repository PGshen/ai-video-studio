/**
 * 与后端 `backend/src/studio/api/schemas.py` 对应的请求/响应类型（任务简报
 * T12，控制者裁定 1：手写，不引入代码生成）。字段名照抄后端的 snake_case，
 * 不做大小写转换——线上传的就是这些名字。
 */

export interface ProjectCreate {
  title: string
  settings?: Record<string, unknown> | null
}

export interface StageOut {
  stage: string
  status: string
  finalized_snapshot_id: string | null
  based_on_snapshot_id: string | null
  finalized_at: string | null
}

export interface ProjectOut {
  id: string
  title: string
  idea_id: string | null
  current_stage: string
  settings: Record<string, unknown>
}

export interface ProjectDetailOut extends ProjectOut {
  stages: StageOut[]
}

export interface FileEntry {
  path: string
  /** `upstream/` 下的文件为 `true`：只读的上游产物副本，PUT 会被拒绝（403）。 */
  readonly: boolean
}

export interface FileTreeOut {
  files: FileEntry[]
}

export interface FileWriteRequest {
  content: string
}

export interface FileWriteResult {
  path: string
}

export interface SnapshotOut {
  id: string
  reason: string
  turn_id: string | null
  created_at: string
}

export interface ModifiedFileOut {
  path: string
  /** 二进制文件（任一侧不是合法 UTF-8 文本）为 `null`，不生成文本 diff。 */
  text_diff: string | null
}

export interface SnapshotDiffOut {
  added: string[]
  removed: string[]
  modified: ModifiedFileOut[]
}

export interface SessionCreate {
  model_profile_id: string
}

export interface SessionOut {
  id: string
  project_id: string | null
  stage: string
  model_profile_id: string
  runtime: string
  sdk_ref: string | null
  status: string
  is_active: boolean
  title: string | null
}

export interface TurnOut {
  id: string
  session_id: string
  user_message: string
  status: string
  start_snapshot_id: string | null
  end_snapshot_id: string | null
  usage: Record<string, unknown> | null
  cost_usd: number | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface SessionDetailOut extends SessionOut {
  turns: TurnOut[]
}

export interface MessageCreate {
  text: string
}

/** `POST .../messages`、`.../cancel`、`.../continue` 的响应：正在处理的 turn id。 */
export interface TurnAccepted {
  turn_id: string
}

export interface ModelProfileOut {
  id: string
  name: string
  provider: string
  model: string
  runtime: string
  supports_vision: boolean
  price_input: number | null
  price_output: number | null
  max_cost_per_turn: number | null
  max_steps_per_turn: number | null
  key_configured: boolean
}
