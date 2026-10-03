<script setup lang="ts">
/**
 * 当前阶段的 [定稿] / [重新打开]（任务简报 T13，控制者裁定 5），放在画布右上角的按钮区
 * （原来在工作台左侧竖栏的「操作」里）：`active`/`stale` 显示「定稿」（先弹确认框），
 * `finalized`/`stale` 显示「重新打开」。被后端拒绝（例如选题简报没通过 `check_brief`，409）
 * 时在按钮旁显示原因。
 */
import { SquareCheckBig, Undo2 } from '@lucide/vue'
import { computed, ref } from 'vue'
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
import { ApiError } from '@/api/http'
import type { StageOut } from '@/types/api'

const props = defineProps<{
  projectId: string
  stages: StageOut[]
  currentStage: string
}>()

const status = computed(() => props.stages.find((s) => s.stage === props.currentStage)?.status)
const canFinalize = computed(() => status.value === 'active' || status.value === 'stale')
const canReopen = computed(() => status.value === 'finalized' || status.value === 'stale')

const finalizeMutation = useFinalizeStageMutation(() => props.projectId)
const reopenMutation = useReopenStageMutation(() => props.projectId)
const actionError = computed(() => {
  if (finalizeMutation.isError.value) return `定稿失败：${errorDetail(finalizeMutation.error.value)}`
  if (reopenMutation.isError.value) return `重新打开失败：${errorDetail(reopenMutation.error.value)}`
  return null
})
const finalizeDialogOpen = ref(false)

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
    // 被拒绝：错误显示在按钮旁，见模板。
  } finally {
    finalizeDialogOpen.value = false
  }
}
</script>

<template>
  <template v-if="canReopen || canFinalize">
    <span
      v-if="actionError"
      class="text-destructive text-xs"
      data-testid="stage-action-error"
    >
      {{ actionError }}
    </span>
    <Button
      v-if="canReopen"
      size="sm"
      variant="outline"
      class="h-7 gap-1 whitespace-nowrap"
      data-testid="reopen-stage"
      :disabled="reopenMutation.isPending.value"
      @click="reopenMutation.mutate(currentStage)"
    >
      <Undo2 class="size-3.5" />
      重新打开
    </Button>
    <Button
      v-if="canFinalize"
      size="sm"
      variant="outline"
      class="h-7 gap-1 whitespace-nowrap"
      data-testid="finalize-stage"
      :disabled="finalizeMutation.isPending.value"
      @click="finalizeDialogOpen = true"
    >
      <SquareCheckBig class="size-3.5" />
      定稿
    </Button>

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
  </template>
</template>
