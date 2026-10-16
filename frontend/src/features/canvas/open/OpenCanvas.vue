<script setup lang="ts">
/**
 * 完全自由项目的画布（open-mode 设计 §7）：只有一个 `FileCanvas`，没有标签栏。头部是「完全自由」
 * 标记和「标记完成 / 重新打开」：完成就是给唯一的 `open` 阶段定稿（后端同时把项目标记为已完成），
 * 没有前置检查，也不弹确认框——随时可以重新打开。`actions` 插槽放快照栏开关；文件画布由页面经
 * `files` 插槽传进来（features 之间不互相 import，同其它阶段画布的「文件」标签）。
 */
import { CircleCheckBig, Undo2 } from '@lucide/vue'
import { computed } from 'vue'
import { ApiError } from '@/api/http'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useFinalizeStageMutation, useReopenStageMutation } from '@/composables/queries'
import type { StageOut } from '@/types/api'

const OPEN_STAGE = 'open'

const props = defineProps<{
  projectId: string
  stages: StageOut[]
  /** 项目有一轮正在跑：按钮禁用（文件画布的只读由页面传给它）。 */
  busy: boolean
}>()

const status = computed(() => props.stages.find((s) => s.stage === OPEN_STAGE)?.status)
const completed = computed(() => status.value === 'finalized')

const finalizeMutation = useFinalizeStageMutation(() => props.projectId)
const reopenMutation = useReopenStageMutation(() => props.projectId)
const pending = computed(() => finalizeMutation.isPending.value || reopenMutation.isPending.value)

const actionError = computed(() => {
  const error = finalizeMutation.isError.value
    ? finalizeMutation.error.value
    : reopenMutation.isError.value
      ? reopenMutation.error.value
      : null
  if (!error) return null
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '操作失败'
})

async function run(action: 'complete' | 'reopen'): Promise<void> {
  try {
    await (action === 'complete' ? finalizeMutation : reopenMutation).mutateAsync(OPEN_STAGE)
  } catch {
    // Shown next to the button, see `actionError`.
  }
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div class="flex shrink-0 items-center gap-2">
      <Badge
        variant="outline"
        data-testid="open-mode-badge"
      >
        完全自由
      </Badge>
      <span
        v-if="completed"
        class="text-muted-foreground text-xs"
      >已完成</span>
      <span class="flex-1" />
      <span
        v-if="actionError"
        class="text-destructive text-xs"
        data-testid="open-action-error"
      >{{ actionError }}</span>
      <Button
        v-if="completed"
        size="sm"
        variant="outline"
        class="h-7 gap-1 whitespace-nowrap"
        data-testid="reopen-open"
        :disabled="busy || pending"
        @click="run('reopen')"
      >
        <Undo2 class="size-3.5" />
        重新打开
      </Button>
      <Button
        v-else
        size="sm"
        variant="outline"
        class="h-7 gap-1 whitespace-nowrap"
        data-testid="complete-open"
        :disabled="busy || pending"
        @click="run('complete')"
      >
        <CircleCheckBig class="size-3.5" />
        标记完成
      </Button>
      <slot name="actions" />
    </div>
    <slot name="files" />
  </div>
</template>
