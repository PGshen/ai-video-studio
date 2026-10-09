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
import { ApiError, type UploadOptions } from '@/api/http'
import type { SessionScope } from '@/composables/sessionScope'
import type {
  FileWriteResult,
  IdeaCreate,
  IdeaOut,
  IdeaUpdate,
  JobOut,
  MessageCreate,
  ModelProfileCreate,
  ModelProfilePatch,
  ProjectCreate,
  ProjectOut,
  ProjectSettingsPatch,
  ProjectStatus,
  SessionCreate,
  SettingsOut,
  SettingsPatch,
} from '@/types/api'

/** 选题池列表的视图：`null` 是未归档（后端默认），`'archived'` 是已归档。 */
export type IdeasView = 'archived' | null

export const queryKeys = {
  /** 所有选题池列表的公共前缀，卡片变化后整体失效。 */
  ideasAll: () => ['ideas'] as const,
  ideas: (view: IdeasView) => ['ideas', view ?? 'active'] as const,
  ideasEvery: () => ['ideas', 'every'] as const,
  topicCheck: (projectId: string) => ['projects', projectId, 'topic', 'check'] as const,
  brainstormSessions: () => ['brainstorm', 'sessions'] as const,
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
  /** 某个范围（项目阶段或头脑风暴）的会话列表。 */
  sessionsFor: (scope: SessionScope) => {
    if (scope.kind === 'brainstorm') return queryKeys.brainstormSessions()
    if (scope.kind === 'style') return ['styles', scope.styleId, 'sessions'] as const
    return queryKeys.sessions(scope.projectId, scope.stage)
  },
  modelProfiles: () => ['model-profiles'] as const,
  settings: () => ['settings'] as const,
  voices: () => ['tts', 'voices'] as const,
  /** 所有项目的建议查询的公共前缀：`suggestion` 事件到达或处理建议后整体失效。 */
  suggestionsAll: () => ['suggestions'] as const,
  suggestions: (projectId: string) => ['suggestions', projectId, 'list'] as const,
  suggestionSummary: (projectId: string) => ['suggestions', projectId, 'summary'] as const,
  /** 风格列表；所有风格相关查询的公共前缀。 */
  styles: () => ['styles'] as const,
  style: (styleId: string) => ['styles', styleId] as const,
  /** 草稿状态（文件列表、是否有改动）；`styleDraftFile` 都在它之下，按它失效就是整份草稿刷新。 */
  styleDraft: (styleId: string) => ['styles', styleId, 'draft'] as const,
  styleDraftFile: (styleId: string, path: string) =>
    ['styles', styleId, 'draft', 'files', path] as const,
  job: (jobId: string) => ['jobs', jobId] as const,
  latestJob: (projectId: string, type: string) =>
    ['projects', projectId, 'jobs', 'latest', type] as const,
  /** `turn_status` 到达时用这个前缀失效，不管当时的镜头集合是什么。 */
  sceneChecksAll: (projectId: string) => ['projects', projectId, 'animation', 'scene-checks'] as const,
  /**
   * `sceneIds` 拼进 key 尾部，这样镜头集合变化时 TanStack 会认出这是一个
   * "新的" query 并重新取数；失效走 `sceneChecksAll` 这个前缀，靠 TanStack
   * 默认的前缀匹配（`exact: false`）覆盖所有镜头集合的变体。
   */
  musicMeta: (projectId: string) => ['projects', projectId, 'music', 'meta'] as const,
  htmlPreviewMeta: (projectId: string) =>
    ['projects', projectId, 'animation', 'html-preview-meta'] as const,
  sceneChecks: (projectId: string, sceneIds: readonly string[]) =>
    [...queryKeys.sceneChecksAll(projectId), sceneIds.join(',')] as const,
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
      // 卡片上显示「已创建 N 个项目」，创建后要刷新。
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideasAll() })
      queryClient.setQueryData(queryKeys.project(project.id), project)
    },
  })
}

export function useSetProjectStatusMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { projectId: string; status: ProjectStatus }) =>
      api.setProjectStatus(vars.projectId, vars.status),
    onSuccess: (project: ProjectOut) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(), exact: true })
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(project.id), exact: true })
    },
  })
}

export function useDeleteProjectMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) => api.deleteProject(projectId),
    onSuccess: (_data, projectId) => {
      // 项目没了：它的详情、文件、会话等缓存都丢掉，别再去请求（会 404）。
      queryClient.removeQueries({ queryKey: queryKeys.project(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(), exact: true })
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
    onSuccess: (result: FileWriteResult) =>
      invalidateAfterWrite(queryClient, toValue(projectId), result.path),
  })
}

/**
 * 手动保存文件后要失效的查询：文件树、该文件内容，以及选题简报的检查结果（检查读的是工作区里的
 * `topic/brief.md`，用户在画布里改完保存后提示条必须跟着刷新——M4 T12 走查发现）。
 */
export async function invalidateAfterWrite(
  queryClient: QueryClient,
  projectId: string,
  path: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.fileTree(projectId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.fileContent(projectId, path) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.topicCheck(projectId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.htmlPreviewMeta(projectId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.musicMeta(projectId) }),
  ])
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

export function useSessionsQuery(scope: MaybeRefOrGetter<SessionScope>) {
  return useQuery({
    queryKey: computed(() => queryKeys.sessionsFor(toValue(scope))),
    queryFn: () => {
      const value = toValue(scope)
      if (value.kind === 'brainstorm') return api.listBrainstormSessions()
      if (value.kind === 'style') return api.listStyleSessions(value.styleId)
      return api.listSessions(value.projectId, value.stage)
    },
  })
}

export function useCreateSessionMutation(scope: MaybeRefOrGetter<SessionScope>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: SessionCreate) => {
      const value = toValue(scope)
      if (value.kind === 'brainstorm') return api.createBrainstormSession(body)
      if (value.kind === 'style') return api.createStyleSession(value.styleId, body)
      return api.createSession(value.projectId, value.stage, body)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessionsFor(toValue(scope)) })
    },
  })
}

export function useDeleteSessionMutation(scope: MaybeRefOrGetter<SessionScope>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => api.deleteSession(sessionId),
    onSuccess: (_data, sessionId) => {
      queryClient.removeQueries({ queryKey: queryKeys.session(sessionId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessionsFor(toValue(scope)) })
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
    mutationFn: (body: MessageCreate & { files?: File[] }) =>
      api.sendMessage(toValue(sessionId), body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(toValue(sessionId)) })
      // 会话标题由后端按第一条消息自动生成：发完消息后列表要重取，标题才会出现。
      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey[query.queryKey.length - 1] === 'sessions',
      })
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

export function useCreateModelProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ModelProfileCreate) => api.createModelProfile(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelProfiles() })
    },
  })
}

export function useUpdateModelProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { id: string; patch: ModelProfilePatch }) =>
      api.updateModelProfile(args.id, args.patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelProfiles() })
    },
  })
}

export function useDeleteModelProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (profileId: string) => api.deleteModelProfile(profileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelProfiles() })
    },
  })
}

// ---- settings（M5）----------------------------------------------------

export function useSettingsQuery() {
  return useQuery({ queryKey: queryKeys.settings(), queryFn: api.getSettings })
}

/**
 * 写入后直接用响应更新缓存（后端返回的是更新后的全部设置）。风格列表里的「默认」标记来自
 * 设置，所以默认风格变了要让风格列表也失效。
 */
export function usePatchSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: SettingsPatch) => api.patchSettings(patch),
    onSuccess: (settings: SettingsOut) => {
      queryClient.setQueryData(queryKeys.settings(), settings)
      void queryClient.invalidateQueries({ queryKey: queryKeys.styles() })
    },
  })
}

// ---- 回退建议（M5）------------------------------------------------------

export function useSuggestionsQuery(projectId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.suggestions(toValue(projectId) ?? '')),
    queryFn: () => api.listSuggestions(toValue(projectId) as string),
    enabled: computed(() => toValue(projectId) !== null),
  })
}

export function useSuggestionSummaryQuery(projectId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => queryKeys.suggestionSummary(toValue(projectId))),
    queryFn: () => api.getSuggestionSummary(toValue(projectId)),
  })
}

/** 建议的处理（去处理后发送 / 忽略）会改列表和阶段角标。 */
function invalidateSuggestions(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.suggestionsAll() })
}

export function useApplySuggestionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (suggestionId: string) => api.applySuggestion(suggestionId),
    onSuccess: () => invalidateSuggestions(queryClient),
  })
}

export function useDismissSuggestionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (suggestionId: string) => api.dismissSuggestion(suggestionId),
    onSuccess: () => invalidateSuggestions(queryClient),
  })
}

export { invalidateSuggestions }

// ---- 会话内换模型、TTS、项目语音设置（M5）------------------------------

/** 换模型后会话列表里的 `model_profile_id` 变了，让列表失效。 */
export function useSwitchSessionModelMutation(scope: MaybeRefOrGetter<SessionScope>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { sessionId: string; modelProfileId: string }) =>
      api.switchSessionModel(args.sessionId, args.modelProfileId),
    onSuccess: (session) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessionsFor(toValue(scope)) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.session(session.id) })
    },
  })
}

export function useVoicesQuery() {
  return useQuery({ queryKey: queryKeys.voices(), queryFn: api.listVoices, staleTime: Infinity })
}

/** 改音色/语速：项目里的设置变了，配音是否过期由叙事画布按 timing 里记录的音色/语速比较。 */
export function usePatchProjectSettingsMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: ProjectSettingsPatch) => api.patchProjectSettings(toValue(projectId), patch),
    onSuccess: (project: ProjectOut) => {
      queryClient.setQueryData(queryKeys.project(project.id), (old: unknown) =>
        old && typeof old === 'object' ? { ...old, ...project } : project,
      )
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(project.id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects() })
    },
  })
}

// ---- styles（磁盘目录 + 草稿）---------------------------------------------

/** 视频类型选项来自后端注册表，进程生命周期内不变。 */
export function useVideoKindsQuery() {
  return useQuery({
    queryKey: ['video-kinds'] as const,
    queryFn: api.getVideoKinds,
    staleTime: Infinity,
  })
}

export function useStylesQuery() {
  return useQuery({ queryKey: queryKeys.styles(), queryFn: api.listStyles })
}

/** 4xx（比如 404「风格不存在」）重试没有意义；只有网络/服务端错误才按默认次数重试。 */
function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 3
}

export function useStyleQuery(styleId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.style(toValue(styleId) ?? '')),
    queryFn: () => api.getStyle(toValue(styleId)!),
    enabled: computed(() => toValue(styleId) !== null),
    retry: retryUnlessClientError,
  })
}

/** 草稿状态（文件列表 + 是否有改动）；只在已经打开草稿（编辑态）时才启用。 */
export function useStyleDraftQuery(
  styleId: MaybeRefOrGetter<string | null>,
  enabled: MaybeRefOrGetter<boolean> = true,
) {
  return useQuery({
    queryKey: computed(() => queryKeys.styleDraft(toValue(styleId) ?? '')),
    queryFn: () => api.getStyleDraft(toValue(styleId)!),
    enabled: computed(() => toValue(styleId) !== null && toValue(enabled)),
    retry: false,
    // 草稿内容由编辑器自己写进缓存，只在 AI 改动或显式失效时重取；窗口聚焦时重取会把还没写出的编辑冲掉。
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}

export function useDraftFileQuery(
  styleId: MaybeRefOrGetter<string | null>,
  path: MaybeRefOrGetter<string | null>,
  enabled: MaybeRefOrGetter<boolean> = true,
) {
  return useQuery({
    queryKey: computed(() =>
      queryKeys.styleDraftFile(toValue(styleId) ?? '', toValue(path) ?? ''),
    ),
    queryFn: () => api.readDraftFile(toValue(styleId)!, toValue(path)!),
    enabled: computed(
      () => toValue(styleId) !== null && toValue(path) !== null && toValue(enabled),
    ),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}

/** AI 改了草稿（`workspace_changed`）或轮次结束后：整份草稿（状态和各文件）重新取。 */
export function invalidateStyleDraft(queryClient: QueryClient, styleId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.styleDraft(styleId) })
}

/** 风格的增删改复制都会改列表；删除还可能清掉默认风格设置，所以一并失效。 */
function invalidateStyles(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.styles() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.settings() })
}

export function useCreateStyleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.createStyle(),
    onSuccess: (draft) => {
      queryClient.setQueryData(queryKeys.styleDraft(draft.id), draft)
    },
  })
}

export function useDuplicateStyleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (styleId: string) => api.duplicateStyle(styleId),
    onSuccess: () => invalidateStyles(queryClient),
  })
}

export function useDeleteStyleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (styleId: string) => api.deleteStyle(styleId),
    onSuccess: (_data, styleId) => {
      queryClient.removeQueries({ queryKey: queryKeys.style(styleId) })
      invalidateStyles(queryClient)
    },
  })
}

/** 打开草稿（没有就从正式版本复制）；列表里的「有未保存草稿」随之失效。 */
export function useOpenStyleDraftMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (styleId: string) => api.openStyleDraft(styleId),
    onSuccess: (draft) => {
      queryClient.setQueryData(queryKeys.styleDraft(draft.id), draft)
      // 草稿文件内容的缓存可能是上次编辑留下的：抽屉关闭期间 AI 可能已经改过，重新打开时必须重取。
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.styleDraft(draft.id), 'files'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.styles(), exact: true })
    },
  })
}

export function useDeleteDraftFileMutation(styleId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (path: string) => api.deleteDraftFile(toValue(styleId), path),
    // 只刷新草稿状态（文件列表）：按前缀失效会连带重取各文件内容，把还在防抖里的编辑冲回服务端旧内容。
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: queryKeys.styleDraft(toValue(styleId)),
        exact: true,
      }),
  })
}

/** 保存草稿：成为正式版本，草稿相关缓存清掉，列表和详情刷新。 */
export function useSaveStyleDraftMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (styleId: string) => api.saveStyleDraft(styleId),
    onSuccess: (style) => {
      queryClient.removeQueries({ queryKey: queryKeys.styleDraft(style.id) })
      queryClient.setQueryData(queryKeys.style(style.id), style)
      invalidateStyles(queryClient)
    },
  })
}

export function useDiscardStyleDraftMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (styleId: string) => api.discardStyleDraft(styleId),
    onSuccess: (_data, styleId) => {
      queryClient.removeQueries({ queryKey: queryKeys.styleDraft(styleId) })
      invalidateStyles(queryClient)
    },
  })
}

// ---- jobs / 成片渲染（任务 T13）-------------------------------------------

/**
 * `useJobQuery` 的轮询间隔：`queued`/`running` 时 1 秒轮询一次（计划正文
 * "1 秒起步"），`done`/`failed`（或还没查到任何数据）时停止——`refetchInterval`
 * 传函数时，TanStack Query 每次决定要不要发下一次请求都会调用它，参数是
 * 当前 query 对象，`query.state.data` 是上一次成功查询的结果。单独导出成
 * 纯函数方便 `.spec.ts` 覆盖状态机（不用挂载组件也能测"什么状态该继续
 * 轮询、什么状态该停"）。
 */
export function jobRefetchIntervalMs(status: string | null | undefined): number | false {
  return status === 'queued' || status === 'running' ? 1000 : false
}

export function useCreateRenderJobMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.createRenderJob(toValue(projectId)),
    onSuccess: (job: JobOut) => {
      queryClient.setQueryData(queryKeys.job(job.id), job)
    },
  })
}

export function useJobQuery(
  projectId: MaybeRefOrGetter<string>,
  jobId: MaybeRefOrGetter<string | null>,
) {
  return useQuery({
    queryKey: computed(() => queryKeys.job(toValue(jobId) ?? '')),
    queryFn: () => api.getJob(toValue(projectId), toValue(jobId)!),
    enabled: computed(() => toValue(jobId) !== null),
    refetchInterval: (query) => jobRefetchIntervalMs(query.state.data?.status),
  })
}

/**
 * 项目最近一次某类型的任务（TD-34）：`FinalRenderPanel.vue` 挂载时用它
 * 恢复 `currentJobId`，不用等用户重新点一次"渲染成片"。只在挂载时取一次
 * ——一旦 `currentJobId` 有了真实值，后续进度轮询交给 `useJobQuery`。
 */
export function useLatestJobQuery(
  projectId: MaybeRefOrGetter<string>,
  type: MaybeRefOrGetter<string>,
) {
  return useQuery({
    queryKey: computed(() => queryKeys.latestJob(toValue(projectId), toValue(type))),
    queryFn: () => api.getLatestJob(toValue(projectId), toValue(type)),
  })
}

export function useFinalizeRenderMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.finalizeRender(toValue(projectId)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(toValue(projectId)) })
    },
  })
}

/**
 * 按镜头聚合的 `validate_scenes`/`render_preview` 最近状态（TD-33）。
 * `sceneIds` 是从 `narrative.json` 解析出的镜头 id 列表，随它一起放进 key。
 */
export function useSceneChecksQuery(
  projectId: MaybeRefOrGetter<string>,
  sceneIds: MaybeRefOrGetter<readonly string[]>,
) {
  return useQuery({
    queryKey: computed(() => queryKeys.sceneChecks(toValue(projectId), toValue(sceneIds))),
    queryFn: () => api.getSceneChecks(toValue(projectId), toValue(sceneIds)),
    enabled: computed(() => toValue(sceneIds).length > 0),
  })
}

/** HTML 动画阶段的实时预览元数据；工作区变化后重新取，409（叙事不可用）不重试。 */
export function useHtmlPreviewMetaQuery(projectId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => queryKeys.htmlPreviewMeta(toValue(projectId))),
    queryFn: () => api.getHtmlPreviewMeta(toValue(projectId)),
    retry: retryUnlessClientError,
  })
}

// ---- music ----------------------------------------------------------------

/** 配乐的元数据；没有合成配乐的项目返回 404，不重试。 */
export function useMusicMetaQuery(projectId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => queryKeys.musicMeta(toValue(projectId))),
    queryFn: () => api.getMusicMeta(toValue(projectId)),
    retry: retryUnlessClientError,
  })
}

/** 手动渲染配乐：成功或失败都刷新（成功改了 `music/` 下的产物，预览的配乐也随之换版）。 */
export function useRenderMusicMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.renderMusic(toValue(projectId)),
    onSettled: () => {
      void invalidateWorkspace(queryClient, toValue(projectId))
    },
  })
}

/**
 * 上传导入音乐的源文件。进度由调用方通过 `onProgress` 取（不进查询缓存）；无论成败都刷新工作区
 * 相关的查询（成功换了 `music/source.*`，配乐 meta 与预览的音乐随之变化）。
 */
export function useUploadMusicSourceMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { file: File; onProgress?: UploadOptions['onProgress']; signal?: AbortSignal }) =>
      api.uploadMusicSource(toValue(projectId), input.file, {
        onProgress: input.onProgress,
        signal: input.signal,
      }),
    onSettled: () => {
      void invalidateWorkspace(queryClient, toValue(projectId))
    },
  })
}

/** 上传（或替换）歌词；无论成败都刷新工作区相关的查询。 */
export function useUploadMusicLyricsMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { file: File; onProgress?: UploadOptions['onProgress']; signal?: AbortSignal }) =>
      api.uploadMusicLyrics(toValue(projectId), input.file, {
        onProgress: input.onProgress,
        signal: input.signal,
      }),
    onSettled: () => {
      void invalidateWorkspace(queryClient, toValue(projectId))
    },
  })
}

export function useDeleteMusicLyricsMutation(projectId: MaybeRefOrGetter<string>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.deleteMusicLyrics(toValue(projectId)),
    onSettled: () => {
      void invalidateWorkspace(queryClient, toValue(projectId))
    },
  })
}

// ---- ideas / 选题池 ----------------------------------------------------

export function useIdeasQuery(view: MaybeRefOrGetter<IdeasView>) {
  return useQuery({
    queryKey: computed(() => queryKeys.ideas(toValue(view))),
    queryFn: () => api.listIdeas(toValue(view) ?? undefined),
  })
}

/** 所有状态的卡片（含已归档）；项目列表和项目「信息」按项目的 `idea_id` 从里面找关联选题。 */
export function useAllIdeasQuery() {
  return useQuery({ queryKey: queryKeys.ideasEvery(), queryFn: () => api.listIdeas('all') })
}

export function useCreateIdeaMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: IdeaCreate) => api.createIdea(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideasAll() })
    },
  })
}

export function useUpdateIdeaMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { id: string; body: IdeaUpdate }): Promise<IdeaOut> =>
      api.updateIdea(args.id, args.body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideasAll() })
    },
  })
}

export function useDeleteIdeaMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ideaId: string) => api.deleteIdea(ideaId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ideasAll() })
    },
  })
}

// ---- topic ---------------------------------------------------------------

export function useTopicCheckQuery(projectId: MaybeRefOrGetter<string>) {
  return useQuery({
    queryKey: computed(() => queryKeys.topicCheck(toValue(projectId))),
    queryFn: () => api.getTopicCheck(toValue(projectId)),
  })
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
    queryClient.invalidateQueries({ queryKey: queryKeys.topicCheck(projectId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.htmlPreviewMeta(projectId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.musicMeta(projectId) }),
  ])
}
