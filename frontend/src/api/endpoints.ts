/**
 * 每个 M1 用到的后端端点对应一个函数（任务简报 T12，控制者裁定 2）。
 * 路径、方法、状态码与 `backend/src/studio/api/{projects,files,snapshots,
 * sessions,profiles}.py` 一一对应。
 */

import { request, requestText } from '@/api/http'
import type {
  FileTreeOut,
  FileWriteResult,
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
  return request(`/projects/${projectId}`)
}

export function finalizeStage(projectId: string, stage: string) {
  return request(`/projects/${projectId}/stages/${stage}/finalize`, { method: 'POST' })
}

export function reopenStage(projectId: string, stage: string) {
  return request(`/projects/${projectId}/stages/${stage}/reopen`, { method: 'POST' })
}

// ---- files --------------------------------------------------------------

export function getFileTree(projectId: string): Promise<FileTreeOut> {
  return request(`/projects/${projectId}/files`)
}

export function getFileContent(projectId: string, path: string): Promise<string> {
  return requestText(`/projects/${projectId}/files/${path}`)
}

export function writeFileContent(
  projectId: string,
  path: string,
  stage: string,
  content: string,
): Promise<FileWriteResult> {
  return request(`/projects/${projectId}/files/${path}`, {
    method: 'PUT',
    query: { stage },
    body: { content },
  })
}

// ---- snapshots ------------------------------------------------------------

export function listSnapshots(projectId: string): Promise<SnapshotOut[]> {
  return request(`/projects/${projectId}/snapshots`)
}

export function diffSnapshots(
  projectId: string,
  fromId: string,
  toId: string,
): Promise<SnapshotDiffOut> {
  return request(`/projects/${projectId}/snapshots/diff`, { query: { from: fromId, to: toId } })
}

export function rollbackSnapshot(projectId: string, snapshotId: string): Promise<SnapshotOut> {
  return request(`/projects/${projectId}/snapshots/${snapshotId}/rollback`, { method: 'POST' })
}

// ---- sessions -------------------------------------------------------------

export function createSession(
  projectId: string,
  stage: string,
  body: SessionCreate,
): Promise<SessionOut> {
  return request(`/projects/${projectId}/stages/${stage}/sessions`, { method: 'POST', body })
}

export function listSessions(projectId: string, stage: string): Promise<SessionOut[]> {
  return request(`/projects/${projectId}/stages/${stage}/sessions`)
}

export function getSession(sessionId: string): Promise<SessionDetailOut> {
  return request(`/sessions/${sessionId}`)
}

export function sendMessage(sessionId: string, body: MessageCreate): Promise<TurnAccepted> {
  return request(`/sessions/${sessionId}/messages`, { method: 'POST', body })
}

export function cancelSession(sessionId: string): Promise<TurnAccepted> {
  return request(`/sessions/${sessionId}/cancel`, { method: 'POST' })
}

export function continueSession(sessionId: string): Promise<TurnAccepted> {
  return request(`/sessions/${sessionId}/continue`, { method: 'POST' })
}

/** SSE 流的 URL（真正的连接由 `api/sse.ts` 的 `openStream` 负责）。 */
export function sessionStreamUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/stream`
}

// ---- model profiles ---------------------------------------------------

export function listModelProfiles(): Promise<ModelProfileOut[]> {
  return request('/model-profiles')
}
