<script setup lang="ts">
/**
 * 项目工作台外壳（任务简报 T13/T14，控制者裁定 1；M2 T12 加了按阶段分派
 * 画布组件）：阶段导航 + 左侧会话面板 + 右侧画布/快照时间线。`animation`
 * 阶段用专属的 `AnimationCanvas`（镜头列表 + 代码编辑器，见该目录），其它
 * 阶段仍用 M1 的通用 `FileCanvas`（文件树 + 编辑器）——这是这个页面第一次
 * 出现"按阶段选组件"的分支，以后 `narrative` 落地专属画布时照这个模式加。
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
import { combineBusy } from '@/features/workbench/turnControls'
import FileCanvas from '@/features/canvas/generic/FileCanvas.vue'
import AnimationCanvas from '@/features/canvas/animation/AnimationCanvas.vue'

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
          <SessionPanel
            :session-id="sessionId"
            :project-id="projectId"
          />
        </div>

        <Card class="flex min-h-0 flex-col">
          <CardHeader>
            <CardTitle>画布</CardTitle>
          </CardHeader>
          <CardContent class="flex min-h-0 flex-1 flex-col gap-3">
            <AnimationCanvas
              v-if="stage === 'animation'"
              :project-id="projectId"
              :busy="canvasBusy"
            />
            <FileCanvas
              v-else
              :project-id="projectId"
              :stage="stage"
              :busy="canvasBusy"
            />
            <SnapshotTimeline
              :project-id="projectId"
              :busy="canvasBusy"
            />
          </CardContent>
        </Card>
      </div>
    </template>
  </div>
</template>
