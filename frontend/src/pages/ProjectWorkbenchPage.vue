<script setup lang="ts">
/**
 * 项目工作台外壳（任务简报 T13，控制者裁定 1）：阶段导航 + 左侧会话面板
 * + 右侧画布占位（通用文件画布/快照时间线由 T14 接入）。
 */
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useProjectQuery } from '@/composables/queries'
import StageNav from '@/features/workbench/StageNav.vue'
import SessionPanel from '@/features/workbench/SessionPanel.vue'
import SessionPicker from '@/features/workbench/SessionPicker.vue'
import { sessionResetKey } from '@/features/workbench/sessionResetKey'

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

        <Card class="min-h-0">
          <CardHeader>
            <CardTitle>画布</CardTitle>
          </CardHeader>
          <CardContent class="text-muted-foreground text-sm">
            通用文件画布和快照时间线将在 T14 接入。
          </CardContent>
        </Card>
      </div>
    </template>
  </div>
</template>
