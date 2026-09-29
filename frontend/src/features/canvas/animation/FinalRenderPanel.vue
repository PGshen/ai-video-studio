<script setup lang="ts">
/**
 * 成片面板（任务 T13）：渲染成片按钮、任务进度条（轮询 `GET .../jobs/{id}`）、
 * 播放器（`output/final.mp4`）、成片定稿按钮（`POST .../finalize-render`）。
 * 挂在 `AnimationCanvas.vue` 镜头列表/编辑器下方。
 *
 * 本组件自己持有"当前正在跟踪的任务 id"（`currentJobId`）——后端没有"查这
 * 个项目最近一次渲染任务"的端点（`api/jobs.py` 只有按 id 查询），只能从
 * "刚创建的那次响应"或者本次会话里点过的那次拿到 id；刷新整个页面后本组
 * 件不会自动恢复"上一个任务还在跑"的进度条（需要再点一次"渲染成片"），
 * 这是当前后端能力的限制，记入计划决策记录，不是本任务遗漏。
 * `useJobQuery` 的轮询间隔由 `composables/queries.ts::jobRefetchIntervalMs`
 * 决定：`queued`/`running` 时 1 秒一次，`done`/`failed` 后自动停止。
 */
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { finalVideoUrl } from '@/api/endpoints'
import { ApiError } from '@/api/http'
import {
  useCreateRenderJobMutation,
  useFinalizeRenderMutation,
  useJobQuery,
  useProjectQuery,
} from '@/composables/queries'
import { canFinalize, isRenderButtonDisabled, jobStatusLabel } from './renderJobState'

const props = defineProps<{
  projectId: string
  /** 当前镜头数（`AnimationCanvas.vue` 的 `scenes.length`）：没有镜头时禁用渲染按钮。 */
  sceneCount: number
}>()

const currentJobId = ref<string | null>(null)

const { data: job } = useJobQuery(() => props.projectId, currentJobId)
const { data: project } = useProjectQuery(() => props.projectId)

const createJobMutation = useCreateRenderJobMutation(() => props.projectId)
const finalizeMutation = useFinalizeRenderMutation(() => props.projectId)

const renderError = ref<string | null>(null)
const finalizeError = ref<string | null>(null)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

const renderDisabled = computed(
  () =>
    isRenderButtonDisabled({ sceneCount: props.sceneCount, jobStatus: job.value?.status }) ||
    createJobMutation.isPending.value,
)

async function onRender(): Promise<void> {
  renderError.value = null
  try {
    const created = await createJobMutation.mutateAsync()
    currentJobId.value = created.id
  } catch (error) {
    renderError.value = describeError(error)
  }
}

const progressPercent = computed(() => Math.round((job.value?.progress ?? 0) * 100))
const statusLabel = computed(() => jobStatusLabel(job.value?.status))

const finalizeDisabled = computed(
  () => !canFinalize(job.value?.status) || finalizeMutation.isPending.value,
)

async function onFinalize(): Promise<void> {
  finalizeError.value = null
  try {
    await finalizeMutation.mutateAsync()
  } catch (error) {
    finalizeError.value = describeError(error)
  }
}

const videoUrl = computed(() => finalVideoUrl(props.projectId))
</script>

<template>
  <div class="flex flex-col gap-2 border-t pt-3">
    <div class="flex items-center justify-between">
      <p class="text-muted-foreground text-xs font-medium">
        成片
      </p>
      <p
        v-if="project?.completed_at"
        class="text-xs text-emerald-700"
      >
        项目已完成
      </p>
    </div>

    <div class="flex items-center gap-2">
      <Button
        size="sm"
        :disabled="renderDisabled"
        @click="onRender"
      >
        渲染成片
      </Button>
      <span
        v-if="statusLabel"
        class="text-muted-foreground text-xs"
      >
        {{ statusLabel }}
      </span>
    </div>

    <p
      v-if="renderError"
      class="text-destructive text-xs"
    >
      {{ renderError }}
    </p>

    <template v-if="job">
      <div class="bg-muted h-2 w-full overflow-hidden rounded">
        <div
          class="bg-primary h-full transition-all"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>

      <p
        v-if="job.status === 'failed'"
        class="text-destructive text-xs"
      >
        渲染失败：{{ job.error }}
      </p>

      <video
        v-if="job.status === 'done'"
        :src="videoUrl"
        controls
        class="w-full rounded"
      />

      <div
        v-if="job.status === 'done'"
        class="flex items-center gap-2"
      >
        <Button
          size="sm"
          variant="outline"
          :disabled="finalizeDisabled"
          @click="onFinalize"
        >
          成片定稿
        </Button>
      </div>
      <p
        v-if="finalizeError"
        class="text-destructive text-xs"
      >
        {{ finalizeError }}
      </p>
    </template>
  </div>
</template>
