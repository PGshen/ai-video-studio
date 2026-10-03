/**
 * 每个 M1 用到的后端端点对应一个函数（任务简报 T12，控制者裁定 2）。
 * 路径、方法、状态码与 `backend/src/studio/api/{projects,files,snapshots,
 * sessions,profiles}.py` 一一对应。
 */

import {
  ApiError,
  BASE_URL,
  encodeFilePath,
  encodePathSegment,
  request,
  requestText,
} from '@/api/http'
import type {
  FileTreeOut,
  FileWriteResult,
  IdeaCreate,
  IdeaOut,
  IdeaStatus,
  IdeaUpdate,
  JobOut,
  MessageCreate,
  ModelProfileCreate,
  ModelProfileOut,
  ModelProfilePatch,
  ProjectCreate,
  ProjectDetailOut,
  ProjectOut,
  ProjectSettingsPatch,
  ProjectStatus,
  SceneChecksResponse,
  SessionCreate,
  SettingsOut,
  SettingsPatch,
  SessionDetailOut,
  SessionOut,
  SnapshotDiffOut,
  SnapshotOut,
  StageOut,
  StylePresetCreate,
  StylePresetOut,
  StylePresetPatch,
  StylePresetSummaryOut,
  SuggestionOut,
  SuggestionStatus,
  TopicCheckOut,
  TurnAccepted,
  VoiceOut,
} from '@/types/api'

// ---- projects ---------------------------------------------------------

export function createProject(body: ProjectCreate): Promise<ProjectOut> {
  return request('/projects', { method: 'POST', body })
}

export function listProjects(): Promise<ProjectOut[]> {
  return request('/projects')
}

export function getProject(projectId: string): Promise<ProjectDetailOut> {
  return request(`/projects/${encodePathSegment(projectId)}`)
}

export function setProjectStatus(projectId: string, status: ProjectStatus): Promise<ProjectOut> {
  return request(`/projects/${encodePathSegment(projectId)}/status`, {
    method: 'PATCH',
    body: { status },
  })
}

export function finalizeStage(projectId: string, stage: string) {
  return request(
    `/projects/${encodePathSegment(projectId)}/stages/${encodePathSegment(stage)}/finalize`,
    { method: 'POST' },
  )
}

export function reopenStage(projectId: string, stage: string) {
  return request(
    `/projects/${encodePathSegment(projectId)}/stages/${encodePathSegment(stage)}/reopen`,
    { method: 'POST' },
  )
}

// ---- files --------------------------------------------------------------

export function getFileTree(projectId: string): Promise<FileTreeOut> {
  return request(`/projects/${encodePathSegment(projectId)}/files`)
}

export function getFileContent(projectId: string, path: string): Promise<string> {
  return requestText(`/projects/${encodePathSegment(projectId)}/files/${encodeFilePath(path)}`)
}

export function writeFileContent(
  projectId: string,
  path: string,
  stage: string,
  content: string,
): Promise<FileWriteResult> {
  return request(`/projects/${encodePathSegment(projectId)}/files/${encodeFilePath(path)}`, {
    method: 'PUT',
    query: { stage },
    body: { content },
  })
}

// ---- snapshots ------------------------------------------------------------

export function listSnapshots(projectId: string): Promise<SnapshotOut[]> {
  return request(`/projects/${encodePathSegment(projectId)}/snapshots`)
}

export function diffSnapshots(
  projectId: string,
  fromId: string,
  toId: string,
): Promise<SnapshotDiffOut> {
  return request(`/projects/${encodePathSegment(projectId)}/snapshots/diff`, {
    query: { from: fromId, to: toId },
  })
}

export function rollbackSnapshot(projectId: string, snapshotId: string): Promise<SnapshotOut> {
  return request(
    `/projects/${encodePathSegment(projectId)}/snapshots/${encodePathSegment(snapshotId)}/rollback`,
    { method: 'POST' },
  )
}

// ---- sessions -------------------------------------------------------------

/** 会话内换模型（同 runtime、同 provider；有排队/运行中的 turn 时 409）。 */
export function switchSessionModel(sessionId: string, modelProfileId: string): Promise<SessionOut> {
  return request(`/sessions/${encodePathSegment(sessionId)}`, {
    method: 'PATCH',
    body: { model_profile_id: modelProfileId },
  })
}

export function createSession(
  projectId: string,
  stage: string,
  body: SessionCreate,
): Promise<SessionOut> {
  return request(
    `/projects/${encodePathSegment(projectId)}/stages/${encodePathSegment(stage)}/sessions`,
    { method: 'POST', body },
  )
}

export function listSessions(projectId: string, stage: string): Promise<SessionOut[]> {
  return request(
    `/projects/${encodePathSegment(projectId)}/stages/${encodePathSegment(stage)}/sessions`,
  )
}

/** 头脑风暴会话（没有项目和阶段，对应 `api/brainstorm.py`）。 */
export function listBrainstormSessions(): Promise<SessionOut[]> {
  return request('/brainstorm/sessions')
}

export function createBrainstormSession(body: SessionCreate): Promise<SessionOut> {
  return request('/brainstorm/sessions', { method: 'POST', body })
}

export function getSession(sessionId: string): Promise<SessionDetailOut> {
  return request(`/sessions/${encodePathSegment(sessionId)}`)
}

export function sendMessage(sessionId: string, body: MessageCreate): Promise<TurnAccepted> {
  return request(`/sessions/${encodePathSegment(sessionId)}/messages`, { method: 'POST', body })
}

export function cancelSession(sessionId: string): Promise<TurnAccepted> {
  return request(`/sessions/${encodePathSegment(sessionId)}/cancel`, { method: 'POST' })
}

export function continueSession(sessionId: string): Promise<TurnAccepted> {
  return request(`/sessions/${encodePathSegment(sessionId)}/continue`, { method: 'POST' })
}

/** SSE 流的 URL（真正的连接由 `api/sse.ts` 的 `openStream` 负责）。 */
export function sessionStreamUrl(sessionId: string): string {
  return `/api/sessions/${encodePathSegment(sessionId)}/stream`
}

// ---- model profiles ---------------------------------------------------

export function listModelProfiles(): Promise<ModelProfileOut[]> {
  return request('/model-profiles')
}

export function createModelProfile(body: ModelProfileCreate): Promise<ModelProfileOut> {
  return request('/model-profiles', { method: 'POST', body })
}

export function updateModelProfile(
  profileId: string,
  body: ModelProfilePatch,
): Promise<ModelProfileOut> {
  return request(`/model-profiles/${encodePathSegment(profileId)}`, { method: 'PATCH', body })
}

export function deleteModelProfile(profileId: string): Promise<void> {
  return request(`/model-profiles/${encodePathSegment(profileId)}`, { method: 'DELETE' })
}

// ---- 回退建议（M5，对应 `api/suggestions.py`）---------------------------

export function listSuggestions(
  projectId: string,
  status?: SuggestionStatus,
): Promise<SuggestionOut[]> {
  return request(`/projects/${encodePathSegment(projectId)}/suggestions`, { query: { status } })
}

/** `{目标阶段: 待处理数量}`，阶段导航角标用；没有待处理建议的阶段不出现。 */
export function getSuggestionSummary(projectId: string): Promise<Record<string, number>> {
  return request(`/projects/${encodePathSegment(projectId)}/suggestions/summary`)
}

export function applySuggestion(suggestionId: string): Promise<SuggestionOut> {
  return request(`/suggestions/${encodePathSegment(suggestionId)}/apply`, { method: 'POST' })
}

export function dismissSuggestion(suggestionId: string): Promise<SuggestionOut> {
  return request(`/suggestions/${encodePathSegment(suggestionId)}/dismiss`, { method: 'POST' })
}

// ---- TTS 与项目语音设置（M5，对应 `api/tts.py`、`api/projects.py`）------------

export function listVoices(): Promise<VoiceOut[]> {
  return request('/tts/voices')
}

/**
 * 试听：真实合成（可能产生费用，后端按音色+语速缓存，同一组合只合成一次）。返回 mp3 的 Blob；
 * 失败时抛 `ApiError`（503 缺 key、502 供应商出错、422 参数不合法）。
 */
export async function previewVoice(voice: string, speed: number): Promise<Blob> {
  const response = await fetch(`${BASE_URL}/tts/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice, speed }),
  })
  if (!response.ok) {
    const text = await response.text()
    let detail: unknown = text
    try {
      detail = (JSON.parse(text) as { detail?: unknown }).detail ?? text
    } catch {
      // 不是 JSON：原样当文本
    }
    throw new ApiError(response.status, detail)
  }
  return response.blob()
}

export function patchProjectSettings(
  projectId: string,
  body: ProjectSettingsPatch,
): Promise<ProjectOut> {
  return request(`/projects/${encodePathSegment(projectId)}/settings`, { method: 'PATCH', body })
}

// ---- style presets（M5，对应 `api/styles.py`）--------------------------

export function listStylePresets(): Promise<StylePresetSummaryOut[]> {
  return request('/style-presets')
}

export function getStylePreset(presetId: string): Promise<StylePresetOut> {
  return request(`/style-presets/${encodePathSegment(presetId)}`)
}

export function createStylePreset(body: StylePresetCreate): Promise<StylePresetOut> {
  return request('/style-presets', { method: 'POST', body })
}

export function updateStylePreset(
  presetId: string,
  body: StylePresetPatch,
): Promise<StylePresetOut> {
  return request(`/style-presets/${encodePathSegment(presetId)}`, { method: 'PATCH', body })
}

export function deleteStylePreset(presetId: string): Promise<void> {
  return request(`/style-presets/${encodePathSegment(presetId)}`, { method: 'DELETE' })
}

export function duplicateStylePreset(presetId: string): Promise<StylePresetOut> {
  return request(`/style-presets/${encodePathSegment(presetId)}/duplicate`, { method: 'POST' })
}

// ---- settings（M5，对应 `api/settings.py`）-----------------------------

export function getSettings(): Promise<SettingsOut> {
  return request('/settings')
}

export function patchSettings(body: SettingsPatch): Promise<SettingsOut> {
  return request('/settings', { method: 'PATCH', body })
}

// ---- jobs / 成片渲染（任务 T13，对应 `api/jobs.py`、`api/animation.py`）----

export function createRenderJob(projectId: string): Promise<JobOut> {
  return request(`/projects/${encodePathSegment(projectId)}/render`, { method: 'POST' })
}

export function getJob(projectId: string, jobId: string): Promise<JobOut> {
  return request(
    `/projects/${encodePathSegment(projectId)}/jobs/${encodePathSegment(jobId)}`,
  )
}

/** 项目最近一次某类型的任务；没有任何任务时返回 `null`（TD-34）。 */
export function getLatestJob(projectId: string, type: string): Promise<JobOut | null> {
  return request(`/projects/${encodePathSegment(projectId)}/jobs/latest`, { query: { type } })
}

export function finalizeRender(projectId: string): Promise<StageOut> {
  return request(`/projects/${encodePathSegment(projectId)}/animation/finalize-render`, {
    method: 'POST',
  })
}

/** 按镜头聚合的 `validate_scenes`/`render_preview` 最近状态（TD-33）。 */
export function getSceneChecks(
  projectId: string,
  sceneIds: readonly string[],
): Promise<SceneChecksResponse> {
  return request(`/projects/${encodePathSegment(projectId)}/animation/scene-checks`, {
    query: { scene_id: [...sceneIds] },
  })
}

/**
 * 成片下载/播放地址（`GET /projects/{id}/output/final.mp4`）：直接给
 * `<video>` 标签当 `src` 用，不用专门写一个 fetch 函数下载字节——同
 * `sessionStreamUrl` 的做法。
 */
export function finalVideoUrl(projectId: string): string {
  return `/api/projects/${encodePathSegment(projectId)}/output/final.mp4`
}

/**
 * 工作区文件的原始字节地址（`GET /projects/{id}/files/{path}`）：直接给
 * `<audio>` 当 `src` 用（叙事阶段的配音 `narrative/audio/<id>.mp3`）。
 * `version` 作为缓存标识拼进查询串（后端忽略它）：同一路径的文件被重新
 * 生成后（例如重新配音，`audio_hash` 变了），浏览器不会继续播缓存里的旧音频。
 */
export function workspaceFileUrl(projectId: string, path: string, version?: string): string {
  const base = `/api/projects/${encodePathSegment(projectId)}/files/${encodeFilePath(path)}`
  return version ? `${base}?v=${encodeURIComponent(version)}` : base
}

// ---- blobs（TD-21：工具结果里的图片，例如 render_preview 关键帧）--------

/**
 * 工具结果图片的地址（`GET /projects/{id}/blobs/{sha256}`）：直接给 `<img>`
 * 当 `src` 用，同 `finalVideoUrl`/`sessionStreamUrl` 的做法。
 */
export function blobUrl(projectId: string, sha256: string): string {
  return `/api/projects/${encodePathSegment(projectId)}/blobs/${encodePathSegment(sha256)}`
}

// ---- ideas / 选题池（M4，对应 `api/ideas.py`）---------------------------

/** 不带 `status` 时后端返回未归档的卡片；`'all'` 含归档。 */
export function listIdeas(status?: IdeaStatus | 'all'): Promise<IdeaOut[]> {
  return request('/ideas', { query: { status } })
}

export function createIdea(body: IdeaCreate): Promise<IdeaOut> {
  return request('/ideas', { method: 'POST', body })
}

export function updateIdea(ideaId: string, body: IdeaUpdate): Promise<IdeaOut> {
  return request(`/ideas/${encodePathSegment(ideaId)}`, { method: 'PATCH', body })
}

// ---- topic（M4，对应 `api/topic.py`）-----------------------------------

/** `topic/brief.md` 的结构检查结果（和 `check_brief` 工具同一份逻辑）。 */
export function getTopicCheck(projectId: string): Promise<TopicCheckOut> {
  return request(`/projects/${encodePathSegment(projectId)}/topic/check`)
}
