/**
 * 与后端 `backend/src/studio/api/schemas.py` 对应的请求/响应类型（任务简报
 * T12，控制者裁定 1：手写，不引入代码生成）。字段名照抄后端的 snake_case，
 * 不做大小写转换——线上传的就是这些名字。
 */

export interface ProjectCreate {
  title: string
  settings?: Record<string, unknown> | null
  /** 从选题池的想法卡片创建（卡片须为 `idea` 状态，成功后变为 `picked`）。 */
  idea_id?: string | null
  /** 风格库里的预设 id；不给就用默认风格，没有默认风格时用占位 `STYLE.md`。 */
  style_preset_id?: string | null
}

/** 风格预设里的一个文件（`references/*` 或 `exemplars/*`）。 */
export interface StyleFile {
  name: string
  text: string
}

/** `GET /api/style-presets` 的一项（不含文件内容）。 */
export interface StylePresetSummaryOut {
  id: string
  name: string
  category: string
  description: string | null
  reference_count: number
  exemplar_count: number
  is_default: boolean
}

/** 一套风格 = skill 形态的目录：入口 `STYLE.md` + `references/` + `exemplars/`（ADR 0011）。 */
export interface StylePresetOut {
  id: string
  name: string
  category: string
  description: string | null
  /** 入口 `STYLE.md` 全文。 */
  content: string
  references: StyleFile[]
  exemplars: StyleFile[]
  is_default: boolean
  created_at: string
}

export interface StylePresetCreate {
  name: string
  category: string
  description?: string | null
  content: string
  references: StyleFile[]
  exemplars: StyleFile[]
}

/** 只含要改的字段；`references`/`exemplars` 给了就整体替换。 */
export interface StylePresetPatch {
  name?: string
  category?: string
  description?: string | null
  content?: string
  references?: StyleFile[]
  exemplars?: StyleFile[]
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
  /** "成片定稿"（T11）后设为完成时间；`null` 表示项目尚未完成（任务 T13）。 */
  completed_at: string | null
}

export interface ProjectDetailOut extends ProjectOut {
  stages: StageOut[]
  /**
   * 项目当前是否有一轮在跑（任一会话）。后端按项目串行，这一个字段就
   * 足够代表"整个项目忙不忙"（T14 控制者裁定：画布/快照时间线只读要看
   * 这个，不能只看当前选中会话的 turn 状态——用户可能开着另一个会话在
   * 跑，或者另一个浏览器标签页在跑）。
   */
  busy: boolean
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

export type SuggestionStatus = 'open' | 'applied' | 'dismissed'

/** 回退建议（后端 `api/schemas.py::SuggestionOut`）：下游阶段的 agent 对上游产物提出的修改建议。 */
export interface SuggestionOut {
  id: string
  project_id: string
  from_stage: string
  to_stage: string
  content: string
  status: SuggestionStatus
  turn_id: string | null
  created_at: string
}

/** `GET /api/tts/voices`（后端 `api/tts.py::VoiceOut`）。 */
export interface VoiceOut {
  alias: string
  /** 中文名，取自旧项目的音色表。 */
  label: string
  gender: string
  engine: string
}

/** `PATCH /api/projects/{id}/settings`：只放行 `voice`/`speech_rate`，`null` 清除该键。 */
export interface ProjectSettingsPatch {
  voice?: string | null
  speech_rate?: number | null
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
  /** `interrupted` 且从未真正开始运行（重启时还在排队）；[继续] 会重发 `user_message`（TD-19）。 */
  never_started: boolean
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

/**
 * `jobs` 表一行（后端 `api/schemas.py::JobOut`，任务 T13）：渲染成片任务的
 * 状态、进度、错误、结果。不含 `payload`/`heartbeat_at`——这两个是 worker
 * 内部字段，前端不需要（后端 `JobOut` 文档同款理由）。
 */
export interface JobOut {
  id: string
  type: string
  project_id: string
  status: string
  progress: number
  error: string | null
  result: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ModelProfileOut {
  id: string
  name: string
  provider: string
  model: string
  runtime: string
  /** 账号密码已被后端打码（`https://***@host/v1`）。 */
  base_url: string | null
  /** 环境变量的**名字**（不是 key 的值）；`null` 表示使用本机登录（仅 claude）。 */
  api_key_env: string | null
  supports_vision: boolean
  price_input: number | null
  price_output: number | null
  max_cost_per_turn: number | null
  max_steps_per_turn: number | null
  key_configured: boolean
  /** 内置配置（种子名和 `fake`）：可以编辑，不能删除。 */
  builtin: boolean
  /** 当前由环境变量（`STUDIO_*`）决定的字段；后端拒绝在界面里改它们。 */
  env_override: string[]
}

export interface ModelProfileCreate {
  name: string
  provider: string
  model: string
  runtime: string
  base_url: string | null
  api_key_env: string | null
  supports_vision: boolean
  price_input: number | null
  price_output: number | null
  max_cost_per_turn: number | null
  max_steps_per_turn: number | null
}

/** 只含要改的字段；`null` 清空可空字段。`name`/`provider`/`runtime` 建好后不可改。 */
export type ModelProfilePatch = Partial<
  Pick<
    ModelProfileCreate,
    | 'model'
    | 'base_url'
    | 'api_key_env'
    | 'supports_vision'
    | 'price_input'
    | 'price_output'
    | 'max_cost_per_turn'
    | 'max_steps_per_turn'
  >
>

export type WebMode = 'tools' | 'native'

export interface TtsDefaultOut {
  voice: string
  speech_rate: number
}

/** `GET /api/settings`（后端 `api/schemas.py::SettingsOut`）。 */
export interface SettingsOut {
  /** `{阶段: 模型配置 id}`，新建会话时预选；没设置的阶段不出现。 */
  stage_default_profile: Record<string, string>
  /** 有效的联网模式：界面覆盖优先，否则是环境变量 `STUDIO_WEB_MODE`。 */
  web_mode: WebMode
  web_mode_source: 'ui' | 'env'
  /** 环境变量给出的默认值，「清除覆盖」后回落到它。 */
  web_mode_env: WebMode
  tts_default: TtsDefaultOut
  default_style_preset_id: string | null
}

/** `PATCH /api/settings`：只改出现的字段，`null` 清除。 */
export interface SettingsPatch {
  stage_default_profile?: Record<string, string | null>
  web_mode?: WebMode | null
  tts_default?: { voice?: string | null; speech_rate?: number | null }
  default_style_preset_id?: string | null
}

/**
 * 按镜头聚合的 `validate_scenes`/`render_preview` 最近状态（TD-33，后端
 * `api/schemas.py::SceneCheckOut`）：读时聚合，不对应任何持久化表。
 */
export interface SceneCheckOut {
  status: 'passed' | 'failed' | 'not_checked'
  /** 检查之后镜头代码又改过，需要重新检查。 */
  stale: boolean
  checked_at: string | null
}

export interface SceneChecksOut {
  validate_scenes: SceneCheckOut
  render_preview: SceneCheckOut
}

export interface SceneChecksResponse {
  scenes: Record<string, SceneChecksOut>
}

// ---- 选题池（M4，对应 `api/ideas.py`）-----------------------------------

export type IdeaStatus = 'idea' | 'picked' | 'archived'
export type IdeaScoreKey = 'counterintuitive' | 'provable' | 'visual' | 'novelty'

export interface IdeaOut {
  id: string
  title: string
  pitch: string | null
  counterintuitive: string | null
  tags: string[]
  scores: Partial<Record<IdeaScoreKey, number>>
  status: IdeaStatus
  /** `picked` 的卡片对应的项目。 */
  project_id: string | null
  source_session_id: string | null
  created_at: string
  updated_at: string
}

export interface IdeaCreate {
  title: string
  pitch?: string | null
  counterintuitive?: string | null
  tags?: string[] | null
  scores?: Partial<Record<IdeaScoreKey, number>> | null
}

/** PATCH：只带要改的字段；`null` 清空文本字段。`status` 只能在 idea/archived 之间切换。 */
export interface IdeaUpdate {
  title?: string
  pitch?: string | null
  counterintuitive?: string | null
  tags?: string[] | null
  scores?: Partial<Record<IdeaScoreKey, number>> | null
  status?: 'idea' | 'archived'
}

// ---- 选题简报检查（M4，对应 `api/topic.py`）------------------------------

export interface TopicCheckOut {
  ok: boolean
  errors: string[]
  warnings: string[]
}
