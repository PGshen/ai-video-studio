<script setup lang="ts">
/**
 * 对话流里的回退建议卡片（计划 M5 T13，设计 §5.4）：来源阶段 → 目标阶段、建议内容、
 * 「去处理」「忽略」。处理状态以 `GET /suggestions` 的最新值为准（事件里的 `status` 只是提出
 * 建议那一刻的值）。「去处理」：目标阶段已定稿要先确认并重新打开；然后跳到目标阶段并预填输入框
 * （见 `ProjectWorkbenchPage`），使用者发送后才标为已处理；目标阶段未开放（locked）时不能去。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage } from '@/api/http'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useDismissSuggestionMutation,
  useProjectQuery,
  useReopenStageMutation,
  useSuggestionsQuery,
} from '@/composables/queries'
import type { SuggestionItem } from '@/composables/useSessionStream'
import { STAGE_TITLES, cardActions, goToAction, suggestionRoute } from './suggestionFlow'

const props = defineProps<{ item: SuggestionItem; projectId: string }>()

const router = useRouter()
const { data: project } = useProjectQuery(() => props.projectId)
const { data: suggestions } = useSuggestionsQuery(() => props.projectId)
const dismissMutation = useDismissSuggestionMutation()
const reopenMutation = useReopenStageMutation(() => props.projectId)

const status = computed(
  () => suggestions.value?.find((s) => s.id === props.item.suggestionId)?.status ?? 'open',
)
const targetStageStatus = computed(
  () => project.value?.stages.find((s) => s.stage === props.item.toStage)?.status,
)
const actions = computed(() => cardActions(status.value, targetStageStatus.value))
const reopenDialogOpen = ref(false)
const error = ref<string | null>(null)

const STATUS_LABELS = { open: '待处理', applied: '已处理', dismissed: '已忽略' } as const

async function navigate(): Promise<void> {
  await router.push(suggestionRoute(props.projectId, props.item.toStage, props.item.suggestionId))
}

async function go(): Promise<void> {
  error.value = null
  const action = goToAction(targetStageStatus.value)
  if (action.kind === 'go') await navigate()
  else if (action.kind === 'reopen_then_go') reopenDialogOpen.value = true
}

async function confirmReopen(): Promise<void> {
  try {
    await reopenMutation.mutateAsync(props.item.toStage)
    reopenDialogOpen.value = false
    await navigate()
  } catch (err) {
    reopenDialogOpen.value = false
    error.value = `重新打开失败：${errorMessage(err)}`
  }
}

async function dismiss(): Promise<void> {
  error.value = null
  try {
    await dismissMutation.mutateAsync(props.item.suggestionId)
  } catch (err) {
    error.value = `忽略失败：${errorMessage(err)}`
  }
}
</script>

<template>
  <div
    class="flex flex-col gap-2 rounded-md border p-3 text-sm"
    :class="status === 'open' ? 'border-sky-300 bg-sky-50 text-sky-950' : 'opacity-60'"
    :data-testid="`suggestion-${item.suggestionId}`"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="font-medium">
        回退建议：{{ STAGE_TITLES[item.fromStage] ?? item.fromStage }} →
        {{ STAGE_TITLES[item.toStage] ?? item.toStage }}
      </span>
      <Badge :variant="status === 'open' ? 'default' : 'secondary'">
        {{ STATUS_LABELS[status] }}
      </Badge>
    </div>
    <p class="whitespace-pre-wrap">
      {{ item.content }}
    </p>
    <div
      v-if="actions.go || actions.dismiss"
      class="flex flex-wrap items-center gap-2"
    >
      <Button
        v-if="actions.go"
        size="sm"
        :disabled="actions.goDisabledReason !== null || reopenMutation.isPending.value"
        :title="actions.goDisabledReason ?? ''"
        data-testid="suggestion-go"
        @click="go"
      >
        去处理
      </Button>
      <Button
        v-if="actions.dismiss"
        size="sm"
        variant="outline"
        :disabled="dismissMutation.isPending.value"
        data-testid="suggestion-dismiss"
        @click="dismiss"
      >
        忽略
      </Button>
      <span
        v-if="actions.goDisabledReason"
        class="text-muted-foreground text-xs"
      >{{ actions.goDisabledReason }}</span>
    </div>
    <p
      v-if="error"
      class="text-destructive text-xs"
    >
      {{ error }}
    </p>

    <AlertDialog v-model:open="reopenDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>先重新打开{{ STAGE_TITLES[item.toStage] ?? item.toStage }}阶段？</AlertDialogTitle>
          <AlertDialogDescription>
            这个阶段已经定稿。处理建议需要先重新打开它；重新定稿之前，下游仍然读上一次定稿的版本。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction @click="confirmReopen">
            重新打开并去处理
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
