<script setup lang="ts">
/**
 * 项目工作台外壳（任务简报 T13/T14，控制者裁定 1；M2 T12 加了按阶段分派
 * 画布组件）：阶段导航 + 会话面板 | 画布 | 快照栏（后三者由 `WorkbenchSplit` 分栏，可拖宽）。`animation`
 * 阶段用专属的 `AnimationCanvas`（镜头列表 + 代码编辑器，见该目录），
 * `narrative` 阶段用 `NarrativeCanvas`（镜头卡片 + 配音播放条 + JSON，M3），
 * 其它阶段仍用 M1 的通用 `FileCanvas`（文件树 + 编辑器）。
 *

 * `busy`（画布/快照时间线是否只读）综合两个信号（T14 审查修复，见
 * `turnControls.combineBusy` 的文档注释）：`project.busy`
 * （`GET /projects/{id}` 返回，后端按项目串行、覆盖任意会话；
 * `useProjectQuery` 开了 3 秒轮询，`useSessionStream` 在当前会话
 * `turn_status` 到达时会让这条查询立刻失效，不用等下一个轮询周期）+
 * 当前选中会话的 turn 状态（SSE，近乎实时，但只覆盖"正在看的这个会
 * 话"）。单独开一条 `useSessionStream` 连接只是为了拿到这第二个信号——
 * 本地单人应用，一个会话同时最多两条 SSE 连接（这条 + `SessionPanel`
 * 内部那条）的开销可以接受；这样 `FileCanvas` 不需要 import
 * `features/workbench`（ESLint 分层规则禁止 features 互相 import），
 * 也不需要把 `SessionPanel` 已经很紧凑的状态往上提。
 */
import { useLocalStorage, useMediaQuery } from '@vueuse/core'
import { PanelLeftClose, PanelLeftOpen } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  useApplySuggestionMutation,
  useModelProfilesQuery,
  useSessionsQuery,
  useProjectQuery,
  useSuggestionsQuery,
} from '@/composables/queries'
import { prefillText } from '@/components/session/suggestionFlow'
import { useSessionStream } from '@/composables/useSessionStream'
import StageFinalizeButton from '@/features/workbench/StageFinalizeButton.vue'
import StageNav from '@/features/workbench/StageNav.vue'
import SessionPanel from '@/components/session/SessionPanel.vue'
import SessionList from '@/components/session/SessionList.vue'
import ModelSwitcher from '@/components/session/ModelSwitcher.vue'
import RailToggleButton from '@/features/workbench/RailToggleButton.vue'
import SnapshotRail from '@/features/workbench/SnapshotRail.vue'
import WorkbenchSplit from '@/features/workbench/WorkbenchSplit.vue'
import { sessionResetKey } from '@/features/workbench/sessionResetKey'
import { combineBusy } from '@/components/session/turnControls'
import { useEnsureSession } from '@/components/session/useEnsureSession'
import { projectScope } from '@/composables/sessionScope'
import FileCanvas from '@/features/canvas/generic/FileCanvas.vue'
import AnimationCanvas from '@/features/canvas/animation/AnimationCanvas.vue'
import HtmlAnimationCanvas from '@/features/canvas/animation/HtmlAnimationCanvas.vue'
import { STAGES_WITH_OWN_ACTIONS } from '@/features/canvas/stageActions'
import ImportMusicCanvas from '@/features/canvas/music/ImportMusicCanvas.vue'
import MusicCanvas from '@/features/canvas/music/MusicCanvas.vue'
import { isImportMusic } from '@/features/canvas/music/importView'
import NarrativeCanvas from '@/features/canvas/narrative/NarrativeCanvas.vue'
import TopicCanvas from '@/features/canvas/topic/TopicCanvas.vue'

const route = useRoute()
const projectId = computed(() => String(route.params.id))
const stage = computed(() => String(route.params.stage))

const { data: project, isPending, isError } = useProjectQuery(projectId)

const sessionId = ref<string | null>(null)
// 切换阶段或切换项目时，上一次选中的会话不应该带到新的项目/阶段组合里
// （审查修复：原来只 watch(stage)，项目 A/topic 切到项目 B/topic 时
// stage 两边都是 "topic"、不触发，A 的 sessionId 会带进 B）。
watch(
  () => sessionResetKey(projectId.value, stage.value),
  () => {
    sessionId.value = null
  },
)

/** 歌曲只在「创意与要求」进行中才能换；定稿后换歌不会让下游变 stale，要先重新打开这一阶段。 */
const conceptOpen = computed(
  () => project.value?.stages.find((s) => s.stage === 'concept')?.status === 'active',
)
const scope = computed(() => projectScope(projectId.value, stage.value))
const createSession = useEnsureSession(scope, sessionId)

// 处理回退建议（M5 T13）：卡片的「去处理」跳到 `?suggestion=<id>`，这里把建议内容预填进输入框；
// 使用者发送后（202）才把建议标为已处理，发送失败则仍是待处理；处理完清掉 query，刷新页面不会重复预填。
const router = useRouter()
const { data: suggestions } = useSuggestionsQuery(projectId)
const applySuggestion = useApplySuggestionMutation()
const activeSuggestion = computed(() => {
  const id = route.query.suggestion
  if (typeof id !== 'string') return null
  const found = suggestions.value?.find((s) => s.id === id)
  return found && found.status === 'open' && found.to_stage === stage.value ? found : null
})
const prefill = computed(() =>
  activeSuggestion.value
    ? { text: prefillText(activeSuggestion.value), key: activeSuggestion.value.id }
    : null,
)

async function onMessageSent(): Promise<void> {
  const current = activeSuggestion.value
  if (!current) return
  try {
    await applySuggestion.mutateAsync(current.id)
  } finally {
    await router.replace({ query: { ...route.query, suggestion: undefined } })
  }
}

// 输入框工具栏里的换模型下拉要当前会话对象；与 SessionList 共用同一份查询缓存。
const { data: profiles } = useModelProfilesQuery()
const { data: sessions } = useSessionsQuery(() => scope.value)
const currentSession = computed(() => sessions.value?.find((s) => s.id === sessionId.value))

// 左侧竖栏折叠：使用者的选择记在 localStorage；窄屏（< lg）竖栏横排在最上面，固定用折叠样式。
const userCollapsed = useLocalStorage('workbench-rail-collapsed', false)
const narrow = useMediaQuery('(max-width: 1023px)')
const railCollapsed = computed(() => narrow.value || userCollapsed.value)

const { turnStatus: canvasTurnStatus } = useSessionStream(sessionId)
const canvasBusy = computed(() =>
  combineBusy(project.value?.busy ?? false, canvasTurnStatus.value?.status ?? null),
)
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">
    <p
      v-if="isPending"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
    <p
      v-else-if="isError || !project"
      class="text-destructive text-sm"
    >
      项目加载失败。
    </p>
    <template v-else>
      <!-- lg 以上：竖栏（阶段 + 项目操作 + 会话，可折叠成图标）| 对话 | 画布 | 快照栏（可折叠），
           后三栏之间的分隔条可拖，各自滚动；窄屏：竖栏固定为折叠样式并横排在最上面，其余上下堆叠，整页滚动。 -->
      <div
        class="grid min-h-0 flex-1 grid-cols-1 gap-4 transition-[grid-template-columns] duration-200 ease-out max-lg:overflow-y-auto lg:grid-rows-[minmax(0,1fr)]"
        :class="
          railCollapsed
            ? 'lg:grid-cols-[3rem_minmax(0,1fr)]'
            : 'lg:grid-cols-[11rem_minmax(0,1fr)]'
        "
      >
        <aside
          class="flex min-h-0 flex-col gap-3 max-lg:min-h-max max-lg:flex-row max-lg:flex-wrap max-lg:items-start max-lg:border-b max-lg:pb-3 lg:overflow-x-hidden lg:overflow-y-auto lg:border-r lg:pr-3"
          :class="railCollapsed ? 'lg:items-center lg:!pr-2' : ''"
          data-testid="workbench-rail"
        >
          <div
            class="flex items-center max-lg:hidden"
            :class="railCollapsed ? 'justify-center' : 'justify-between pl-1'"
          >
            <span
              v-if="!railCollapsed"
              class="text-sm font-medium whitespace-nowrap"
            >导航</span>
            <Button
              variant="ghost"
              size="icon-sm"
              :title="railCollapsed ? '展开侧栏' : '收起侧栏'"
              data-testid="toggle-rail"
              @click="userCollapsed = !userCollapsed"
            >
              <PanelLeftOpen v-if="railCollapsed" />
              <PanelLeftClose v-else />
            </Button>
          </div>
          <StageNav
            :project-id="projectId"
            :stages="project.stages"
            :current-stage="stage"
            :collapsed="railCollapsed"
          />
          <SessionList
            v-model:session-id="sessionId"
            class="lg:flex-1"
            :scope="scope"
            :collapsed="railCollapsed"
          />
        </aside>

        <WorkbenchSplit>
          <template #chat>
            <SessionPanel
              class="min-w-0"
              :session-id="sessionId"
              :project-id="projectId"
              :prefill="prefill"
              :create-session="createSession"
              @sent="onMessageSent"
            >
              <template #tools>
                <ModelSwitcher
                  v-if="currentSession && profiles"
                  :key="currentSession.id"
                  :session="currentSession"
                  :profiles="profiles"
                  :scope="scope"
                  compact
                />
              </template>
            </SessionPanel>
          </template>

          <template #canvas="{ railCollapsed: snapshotsHidden, toggleRail, narrow: stacked }">
            <Card class="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden py-4">
              <CardContent class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
                <!-- 快照栏默认隐藏，开关放在画布右上角；topic、narrative、music、produce、animation 阶段并进标签行（见画布的 actions 插槽）。动画阶段（`animation`/`animation_html`/`produce`）没有定稿按钮：只能在“成片”标签里渲染后定稿，否则可以绕过成片直接定稿。 -->
                <div
                  v-if="!STAGES_WITH_OWN_ACTIONS.includes(stage)"
                  class="flex shrink-0 items-center justify-end gap-2"
                >
                  <StageFinalizeButton
                    :project-id="projectId"
                    :stages="project.stages"
                    :current-stage="stage"
                  />
                  <RailToggleButton
                    v-if="!stacked"
                    :collapsed="snapshotsHidden"
                    @toggle="toggleRail"
                  />
                </div>
                <!-- 歌曲项目（MV）的歌曲在「创意与要求」阶段上传并分析：上传区与分析摘要放在文件画布上方。 -->
                <div
                  v-if="stage === 'concept' && isImportMusic(project.settings)"
                  class="max-h-96 shrink-0 overflow-y-auto rounded border p-3"
                  data-testid="concept-song"
                >
                  <ImportMusicCanvas
                    :project-id="projectId"
                    :busy="canvasBusy"
                    :allow-upload="conceptOpen"
                    compact
                  />
                </div>
                <AnimationCanvas
                  v-if="stage === 'animation'"
                  :project-id="projectId"
                  :busy="canvasBusy"
                >
                  <template #actions>
                    <StageFinalizeButton
                      :project-id="projectId"
                      :stages="project.stages"
                      :current-stage="stage"
                      reopen-only
                    />
                    <RailToggleButton
                      v-if="!stacked"
                      :collapsed="snapshotsHidden"
                      @toggle="toggleRail"
                    />
                  </template>
                </AnimationCanvas>
                <HtmlAnimationCanvas
                  v-else-if="stage === 'animation_html' || stage === 'produce'"
                  :project-id="projectId"
                  :busy="canvasBusy"
                  :stage="stage === 'produce' ? 'produce' : 'animation_html'"
                >
                  <template
                    v-if="stage === 'produce'"
                    #music
                  >
                    <ImportMusicCanvas
                      v-if="isImportMusic(project.settings)"
                      :project-id="projectId"
                      :busy="canvasBusy"
                      :allow-upload="false"
                      compact
                    />
                    <MusicCanvas
                      v-else
                      :project-id="projectId"
                      :busy="canvasBusy"
                      stage="produce"
                    />
                  </template>
                  <template #actions>
                    <StageFinalizeButton
                      :project-id="projectId"
                      :stages="project.stages"
                      :current-stage="stage"
                      reopen-only
                    />
                    <RailToggleButton
                      v-if="!stacked"
                      :collapsed="snapshotsHidden"
                      @toggle="toggleRail"
                    />
                  </template>
                </HtmlAnimationCanvas>
                <MusicCanvas
                  v-else-if="stage === 'music'"
                  :project-id="projectId"
                  :busy="canvasBusy"
                >
                  <template #actions>
                    <StageFinalizeButton
                      :project-id="projectId"
                      :stages="project.stages"
                      :current-stage="stage"
                    />
                    <RailToggleButton
                      v-if="!stacked"
                      :collapsed="snapshotsHidden"
                      @toggle="toggleRail"
                    />
                  </template>
                </MusicCanvas>
                <NarrativeCanvas
                  v-else-if="stage === 'narrative'"
                  :project-id="projectId"
                  :busy="canvasBusy"
                >
                  <template #actions>
                    <StageFinalizeButton
                      :project-id="projectId"
                      :stages="project.stages"
                      :current-stage="stage"
                    />
                    <RailToggleButton
                      v-if="!stacked"
                      :collapsed="snapshotsHidden"
                      @toggle="toggleRail"
                    />
                  </template>
                </NarrativeCanvas>
                <TopicCanvas
                  v-else-if="stage === 'topic'"
                  :project-id="projectId"
                  :busy="canvasBusy"
                >
                  <template #actions>
                    <StageFinalizeButton
                      :project-id="projectId"
                      :stages="project.stages"
                      :current-stage="stage"
                    />
                    <RailToggleButton
                      v-if="!stacked"
                      :collapsed="snapshotsHidden"
                      @toggle="toggleRail"
                    />
                  </template>
                </TopicCanvas>
                <FileCanvas
                  v-else
                  :project-id="projectId"
                  :stage="stage"
                  :busy="canvasBusy"
                />
              </CardContent>
            </Card>
          </template>

          <template #rail="{ collapsed, toggle, narrow: railNarrow }">
            <SnapshotRail
              :project-id="projectId"
              :busy="canvasBusy"
              :collapsed="collapsed"
              :narrow="railNarrow"
              @toggle="toggle"
            />
          </template>
        </WorkbenchSplit>
      </div>
    </template>
  </div>
</template>
