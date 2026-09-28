/**
 * 每个 M1 用到的后端端点对应一个函数（任务简报 T12，控制者裁定 2）。
 * 路径、方法、状态码与 `backend/src/studio/api/{projects,files,snapshots,
 * sessions,profiles}.py` 一一对应。
 */

import { encodeFilePath, encodePathSegment, request, requestText } from '@/api/http'
import type {
  FileTreeOut,
  FileWriteResult,
  JobOut,
  MessageCreate,
  ModelProfileOut,
  ProjectCreate,
  ProjectDetailOut,
  ProjectOut,
  SessionCreate,
  SessionDetailOut,
  SessionOut,
  SnapshotDiffOut,
  SnapshotOut,
  StageOut,
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

// ---- jobs / 成片渲染（任务 T13，对应 `api/jobs.py`、`api/animation.py`）----

export function createRenderJob(projectId: string): Promise<JobOut> {
  return request(`/projects/${encodePathSegment(projectId)}/render`, { method: 'POST' })
}

export function getJob(projectId: string, jobId: string): Promise<JobOut> {
  return request(
    `/projects/${encodePathSegment(projectId)}/jobs/${encodePathSegment(jobId)}`,
  )
}

export function finalizeRender(projectId: string): Promise<StageOut> {
  return request(`/projects/${encodePathSegment(projectId)}/animation/finalize-render`, {
    method: 'POST',
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
