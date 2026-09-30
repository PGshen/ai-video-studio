<script setup lang="ts">
/**
 * 阶段导航条 + 当前阶段的 [定稿]/[重新打开]（任务简报 T13，控制者裁定 5）。
 * 样式/可点性映射交给纯函数 `stageStatusStyle`（见同目录 spec），这里只
 * 负责渲染和路由跳转、发起 finalize/reopen mutation。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  useFinalizeStageMutation,
  useReopenStageMutation,
  useSuggestionSummaryQuery,
} from '@/composables/queries'
import { badgeCount } from '@/components/session/suggestionFlow'
import type { StageOut } from '@/types/api'
import { ApiError } from '@/api/http'
import ProjectSettingsDialog from './ProjectSettingsDialog.vue'
import { stageStatusStyle } from './stageStatus'

const props = defineProps<{
  projectId: string
  stages: StageOut[]
  currentStage: string
}>()

const STAGE_TITLES: Record<string, string> = {
  topic: '选题',
  narrative: '叙事',
  animation: '动画',
}

const router = useRouter()

const currentStageInfo = computed(() => props.stages.find((s) => s.stage === props.currentStage))

/** 阶段按钮上的角标：下游提给该阶段、还没处理的回退建议数量（M5 T13）。 */
const { data: suggestionSummary } = useSuggestionSummaryQuery(() => props.projectId)

const finalizeMutation = useFinalizeStageMutation(() => props.projectId)
const reopenMutation = useReopenStageMutation(() => props.projectId)
const finalizeDialogOpen = ref(false)
const settingsDialogOpen = ref(false)

function goToStage(stage: StageOut): void {
  if (stageStatusStyle(stage.status).disabled) return
  void router.push(`/projects/${props.projectId}/${stage.stage}`)
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

async function confirmFinalize(): Promise<void> {
  try {
    await finalizeMutation.mutateAsync(props.currentStage)
  } catch {
    // 被拒绝（例如选题简报没通过 `check_brief`，409）：错误显示在导航条上，见模板。
  } finally {
    finalizeDialogOpen.value = false
  }
}
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
    <nav class="flex items-center gap-2 text-sm">
      <template
        v-for="(stage, index) in stages"
        :key="stage.stage"
      >
        <span
          v-if="index > 0"
          class="text-muted-foreground"
        >─</span>
        <button
          type="button"
          :class="[stageStatusStyle(stage.status).className, 'rounded px-2 py-1']"
          :disabled="stageStatusStyle(stage.status).disabled"
          @click="goToStage(stage)"
        >
          {{ STAGE_TITLES[stage.stage] ?? stage.stage }}{{ stageStatusStyle(stage.status).suffix }}
          <span
            v-if="badgeCount(suggestionSummary, stage.stage) > 0"
            class="ml-1 rounded-full bg-sky-600 px-1.5 text-xs text-white"
            :title="`${badgeCount(suggestionSummary, stage.stage)} 条待处理的回退建议`"
            :data-testid="`suggestion-badge-${stage.stage}`"
          >{{ badgeCount(suggestionSummary, stage.stage) }}</span>
        </button>
      </template>
    </nav>

    <div
      v-if="currentStageInfo"
      class="flex items-center gap-2"
    >
      <p
        v-if="finalizeMutation.isError.value"
        class="text-destructive text-sm"
      >
        定稿失败：{{ errorDetail(finalizeMutation.error.value) }}
      </p>
      <p
        v-if="reopenMutation.isError.value"
        class="text-destructive text-sm"
      >
        重新打开失败：{{ errorDetail(reopenMutation.error.value) }}
      </p>
      <Button
        variant="ghost"
        data-testid="open-project-settings"
        @click="settingsDialogOpen = true"
      >
        项目设置
      </Button>
      <Button
        v-if="currentStageInfo.status === 'finalized' || currentStageInfo.status === 'stale'"
        variant="outline"
        :disabled="reopenMutation.isPending.value"
        @click="reopenMutation.mutate(currentStage)"
      >
        重新打开
      </Button>
      <Button
        v-if="currentStageInfo.status === 'active' || currentStageInfo.status === 'stale'"
        :disabled="finalizeMutation.isPending.value"
        @click="finalizeDialogOpen = true"
      >
        定稿
      </Button>
    </div>

    <ProjectSettingsDialog
      v-model:open="settingsDialogOpen"
      :project-id="projectId"
    />

    <AlertDialog v-model:open="finalizeDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认定稿？</AlertDialogTitle>
          <AlertDialogDescription>
            定稿后这个阶段会被标记为已完成，下游阶段可以基于当前快照继续；仍然可以之后重新打开。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction @click="confirmFinalize">
            确认定稿
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
