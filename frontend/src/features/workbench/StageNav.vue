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
import { useFinalizeStageMutation, useReopenStageMutation } from '@/composables/queries'
import type { StageOut } from '@/types/api'
import { ApiError } from '@/api/http'
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

const finalizeMutation = useFinalizeStageMutation(() => props.projectId)
const reopenMutation = useReopenStageMutation(() => props.projectId)
const finalizeDialogOpen = ref(false)

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
  await finalizeMutation.mutateAsync(props.currentStage)
  finalizeDialogOpen.value = false
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
