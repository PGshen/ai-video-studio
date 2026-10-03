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
  SessionCreate,
  SettingsOut,
  SettingsPatch,
  StylePresetCreate,
  StylePresetPatch,
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
  sessionsFor: (scope: SessionScope) =>
    scope.kind === 'brainstorm'
      ? queryKeys.brainstormSessions()
      : queryKeys.sessions(scope.projectId, scope.stage),
  modelProfiles: () => ['model-profiles'] as const,
  settings: () => ['settings'] as const,
  voices: () => ['tts', 'voices'] as const,
  /** 所有项目的建议查询的公共前缀：`suggestion` 事件到达或处理建议后整体失效。 */
  suggestionsAll: () => ['suggestions'] as const,
  suggestions: (projectId: string) => ['suggestions', projectId, 'list'] as const,
  suggestionSummary: (projectId: string) => ['suggestions', projectId, 'summary'] as const,
  stylePresets: () => ['style-presets'] as const,
  stylePreset: (presetId: string) => ['style-presets', presetId] as const,
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
      return value.kind === 'brainstorm'
        ? api.listBrainstormSessions()
        : api.listSessions(value.projectId, value.stage)
    },
  })
}

export function useCreateSessionMutation(scope: MaybeRefOrGetter<SessionScope>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: SessionCreate) => {
      const value = toValue(scope)
      return value.kind === 'brainstorm'
        ? api.createBrainstormSession(body)
        : api.createSession(value.projectId, value.stage, body)
    },
    onSuccess: () => {
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.stylePresets() })
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

// ---- style presets（M5）-----------------------------------------------

export function useStylePresetsQuery() {
  return useQuery({ queryKey: queryKeys.stylePresets(), queryFn: api.listStylePresets })
}

export function useStylePresetQuery(presetId: MaybeRefOrGetter<string | null>) {
  return useQuery({
    queryKey: computed(() => queryKeys.stylePreset(toValue(presetId) ?? '')),
    queryFn: () => api.getStylePreset(toValue(presetId) as string),
    enabled: computed(() => toValue(presetId) !== null),
  })
}

/** 风格的增删改复制都会改列表；删除还可能清掉默认风格设置，所以一并失效。 */
function invalidateStyles(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.stylePresets() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.settings() })
}

export function useCreateStylePresetMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: StylePresetCreate) => api.createStylePreset(body),
    onSuccess: () => invalidateStyles(queryClient),
  })
}

export function useUpdateStylePresetMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { id: string; patch: StylePresetPatch }) =>
      api.updateStylePreset(args.id, args.patch),
    onSuccess: () => invalidateStyles(queryClient),
  })
}

export function useDeleteStylePresetMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (presetId: string) => api.deleteStylePreset(presetId),
    onSuccess: () => invalidateStyles(queryClient),
  })
}

export function useDuplicateStylePresetMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (presetId: string) => api.duplicateStylePreset(presetId),
    onSuccess: () => invalidateStyles(queryClient),
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
  ])
}
