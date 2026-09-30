/**
 * 每个 M1 用到的后端端点对应一个函数（任务简报 T12，控制者裁定 2）。
 * 路径、方法、状态码与 `backend/src/studio/api/{projects,files,snapshots,
 * sessions,profiles}.py` 一一对应。
 */

import { encodeFilePath, encodePathSegment, request, requestText } from '@/api/http'
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
  TopicCheckOut,
  TurnAccepted,
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

/** 不带 `status` 时后端返回 idea + picked（不含归档）；`'all'` 含归档。 */
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
