<script setup lang="ts">
/**
 * 项目工作台外壳（任务简报 T13/T14，控制者裁定 1）：阶段导航 + 左侧会话
 * 面板 + 右侧通用文件画布/快照时间线。
 *
 * `busy`（画布是否只读）单独开一条 `useSessionStream` 连接读取当前会话
 * 的 turn 状态——本地单人应用，一个会话同时最多两条 SSE 连接（这条 +
 * `SessionPanel` 内部那条）的开销可以接受；这样 `FileCanvas` 不需要
 * import `features/workbench`（ESLint 分层规则禁止 features 互相
 * import），也不需要把 `SessionPanel` 已经很紧凑的状态往上提。
 */
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useProjectQuery } from '@/composables/queries'
import { useSessionStream } from '@/composables/useSessionStream'
import StageNav from '@/features/workbench/StageNav.vue'
import SessionPanel from '@/features/workbench/SessionPanel.vue'
import SessionPicker from '@/features/workbench/SessionPicker.vue'
import SnapshotTimeline from '@/features/workbench/SnapshotTimeline.vue'
import { sessionResetKey } from '@/features/workbench/sessionResetKey'
import { isBusyStatus } from '@/features/workbench/turnControls'
import FileCanvas from '@/features/canvas/generic/FileCanvas.vue'

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

const { turnStatus: canvasTurnStatus } = useSessionStream(sessionId)
const canvasBusy = computed(() => isBusyStatus(canvasTurnStatus.value?.status ?? null))
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
      <StageNav
        :project-id="projectId"
        :stages="project.stages"
        :current-stage="stage"
      />

      <div class="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <div class="flex min-h-0 flex-col gap-2">
          <SessionPicker
            v-model:session-id="sessionId"
            :project-id="projectId"
            :stage="stage"
          />
          <SessionPanel :session-id="sessionId" />
        </div>

        <Card class="flex min-h-0 flex-col">
          <CardHeader>
            <CardTitle>画布</CardTitle>
          </CardHeader>
          <CardContent class="flex min-h-0 flex-1 flex-col gap-3">
            <FileCanvas
              :project-id="projectId"
              :stage="stage"
              :busy="canvasBusy"
            />
            <SnapshotTimeline :project-id="projectId" />
          </CardContent>
        </Card>
      </div>
    </template>
  </div>
</template>
