/**
 * TanStack Query hooks + 中心化的 query-key 工厂（任务简报 T12，控制者裁定
 * 5）。`VueQueryPlugin` 已在 `main.ts` 安装。这里只包一层薄封装：每个 hook
 * 对应 `api/endpoints.ts` 里的一个函数，key 全部从 `queryKeys` 派生，方便
 * `useSessionStream` 在 `workspace_changed`/`snapshot` 到达时按同样的规则
 * 失效缓存。
 */

import { computed, toValue, type MaybeRefOrGetter } from 'vue'
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/vue-query'
import * as api from '@/api/endpoints'
import type {
  FileWriteResult,
  MessageCreate,
  ProjectCreate,
  ProjectOut,
  SessionCreate,
} from '@/types/api'

export const queryKeys = {
  projects: () => ['projects'] as const,
  project: (projectId: string) => ['projects', projectId] as const,
  fileTree: (projectId: string) => ['projects', projectId, 'files'] as const,
  fileContent: (projectId: string, path: string) =>
    ['projects', projectId, 'files', path] as const,
  snapshots: (projectId: string) => ['projects', projectId, 'snapshots'] as const,
  snapshotDiff: (projectId: string, fromId: string, toId: string) =>
    ['projects', projectId, 'snapshots', 'diff', fromId, toId] as const,
  sessions: (projectId: string, stage: string) =>
    ['projects', projectId, 'stages', stage, 'sessions'] as const,
  session: (sessionId: string) => ['sessions', sessionId] as const,
  modelProfiles: () => ['model-profiles'] as const,
}

// ---- projects ---------------------------------------------------------

export function useProjectsQuery() {
  return useQuery({ queryKey: queryKeys.projects(), queryFn: api.listProjects })
}

export function useProjectQuery(projectId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.project(toValue(projectId) ?? '')),
    queryFn: () => api.getProject(toValue(projectId)!),
    enabled: computed(() => toValue(projectId) !== null),
    // `ProjectDetailOut.busy` 反映"项目里任一会话是否有一轮在跑"（T14
    // 审查修复），当前选中会话之外的忙状态（另一个会话、另一个浏览器
    // 标签页）只能靠轮询发现——SSE 只推当前打开的这条会话的事件。3 秒
    // 的滞后对"画布该不该只读"这种场景可以接受；当前会话自己的忙状态
    // 由 `useSessionStream` 的 `turn_status` 事件触发即时失效（见该
    // 文件），不依赖轮询周期。
    refetchInterval: 3000,
  })
}

export function useCreateProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectCreate) => api.createProject(body),
    onSuccess: (project: ProjectOut) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() })
      queryClient.setQueryData(queryKeys.project(project.id), project)
    },
  })
}

export function useFinalizeStageMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (stage: string) => api.finalizeStage(toValue(projectId), stage),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(toValue(projectId)) })
    },
  })
}

export function useReopenStageMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (stage: string) => api.reopenStage(toValue(projectId), stage),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(toValue(projectId)) })
    },
  })
}

// ---- files --------------------------------------------------------------

export function useFileTreeQuery(projectId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.fileTree(toValue(projectId) ?? '')),
    queryFn: () => api.getFileTree(toValue(projectId)!),
    enabled: computed(() => toValue(projectId) !== null),
  })
}

export function useFileContentQuery(
  projectId: MaybeRefOrGetter<string | null>,
  path: MaybeRefOrGetter<string | null>,
) {
  return useQuery({
    queryKey: computed(() => queryKeys.fileContent(toValue(projectId) ?? '', toValue(path) ?? '')),
    queryFn: () => api.getFileContent(toValue(projectId)!, toValue(path)!),
    enabled: computed(() => toValue(projectId) !== null && toValue(path) !== null),
  })
}

export function useWriteFileMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ path, stage, content }: { path: string; stage: string; content: string }) =>
      api.writeFileContent(toValue(projectId), path, stage, content),
    onSuccess: (result: FileWriteResult) => {
      const pid = toValue(projectId)
      void queryClient.invalidateQueries({ queryKey: queryKeys.fileTree(pid) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.fileContent(pid, result.path) })
    },
  })
}

// ---- snapshots ------------------------------------------------------------

export function useSnapshotsQuery(projectId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.snapshots(toValue(projectId) ?? '')),
    queryFn: () => api.listSnapshots(toValue(projectId)!),
    enabled: computed(() => toValue(projectId) !== null),
  })
}

export function useSnapshotDiffQuery(
  projectId: MaybeRefOrGetter<string>,
  fromId: MaybeRefOrGetter<string | null>,
  toId: MaybeRefOrGetter<string | null>,
) {
  return useQuery({
    queryKey: computed(() =>
      queryKeys.snapshotDiff(toValue(projectId), toValue(fromId) ?? '', toValue(toId) ?? ''),
    ),
    queryFn: () => api.diffSnapshots(toValue(projectId), toValue(fromId)!, toValue(toId)!),
    enabled: computed(() => toValue(fromId) !== null && toValue(toId) !== null),
  })
}

export function useRollbackSnapshotMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (snapshotId: string) => api.rollbackSnapshot(toValue(projectId), snapshotId),
    onSuccess: () => {
      void invalidateWorkspace(queryClient, toValue(projectId))
    },
  })
}

// ---- sessions -------------------------------------------------------------

export function useSessionsQuery(
  projectId: MaybeRefOrGetter<string>,
  stage: MaybeRefOrGetter<string>,
) {
  return useQuery({
    queryKey: computed(() => queryKeys.sessions(toValue(projectId), toValue(stage))),
    queryFn: () => api.listSessions(toValue(projectId), toValue(stage)),
  })
}

export function useCreateSessionMutation(
  projectId: MaybeRefOrGetter<string>,
  stage: MaybeRefOrGetter<string>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: SessionCreate) => api.createSession(toValue(projectId), toValue(stage), body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sessions(toValue(projectId), toValue(stage)),
      })
    },
  })
}

export function useSessionQuery(sessionId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.session(toValue(sessionId) ?? '')),
    queryFn: () => api.getSession(toValue(sessionId)!),
    enabled: computed(() => toValue(sessionId) !== null),
  })
}

export function useSendMessageMutation(sessionId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: MessageCreate) => api.sendMessage(toValue(sessionId), body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(toValue(sessionId)) })
    },
  })
}

export function useCancelSessionMutation(sessionId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.cancelSession(toValue(sessionId)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(toValue(sessionId)) })
    },
  })
}

export function useContinueSessionMutation(sessionId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.continueSession(toValue(sessionId)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(toValue(sessionId)) })
    },
  })
}

// ---- model profiles ---------------------------------------------------

export function useModelProfilesQuery() {
  return useQuery({ queryKey: queryKeys.modelProfiles(), queryFn: api.listModelProfiles })
}

// ---- shared helper for useSessionStream --------------------------------

/**
 * `workspace_changed`/`snapshot` 到达时要失效的 query key 集合：文件树、
 * 打开的文件内容（前缀匹配整个 `['projects', id, 'files']` 分支）、快照
 * 列表。`useSessionStream` 用这个函数，保证和上面各 hook 用的 key 规则
 * 完全一致。
 */
export async function invalidateWorkspace(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  await Promise.all([
    // TanStack Query 默认按前缀模糊匹配：这个 key 同时覆盖 `fileTree` 本身
    // 和所有 `fileContent(projectId, <path>)`（key 以它为前缀）。
    queryClient.invalidateQueries({ queryKey: queryKeys.fileTree(projectId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.snapshots(projectId) }),
  ])
}
