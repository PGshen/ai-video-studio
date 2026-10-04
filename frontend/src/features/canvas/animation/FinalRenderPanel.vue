<script setup lang="ts">
/**
 * 成片面板（任务 T13）：渲染成片按钮、任务进度条（轮询 `GET .../jobs/{id}`）、
 * 播放器（`output/final.mp4`）、成片定稿按钮（`POST .../finalize-render`）。
 * 在 `AnimationCanvas.vue` 里是独立的“成片”标签。
 *
 * 本组件自己持有"当前正在跟踪的任务 id"（`currentJobId`），但挂载时会先用
 * `useLatestJobQuery`（TD-34：`GET .../jobs/latest`）问一次"这个项目最近
 * 一次 `final_render` 任务是什么"，拿到就直接采用——刷新页面后不用重新点
 * 一次"渲染成片"才能看到上一次的进度/成片。只在 `currentJobId` 还是
 * `null` 时采用这个结果，不覆盖用户在本次挂载期间刚点出来的新任务（这个
 * watcher 只应该生效一次，见下面的 `latestJobAdopted`）。
 * `useJobQuery` 的轮询间隔由 `composables/queries.ts::jobRefetchIntervalMs`
 * 决定：`queued`/`running` 时 1 秒一次，`done`/`failed` 后自动停止。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { finalVideoUrl } from '@/api/endpoints'
import { ApiError } from '@/api/http'
import {
  useCreateRenderJobMutation,
  useFinalizeRenderMutation,
  useJobQuery,
  useLatestJobQuery,
  useProjectQuery,
} from '@/composables/queries'
import { canFinalize, isRenderButtonDisabled, jobStatusLabel } from './renderJobState'

const RENDER_JOB_TYPE = 'final_render'

const props = defineProps<{
  projectId: string
  /** 当前镜头数（`AnimationCanvas.vue` 的 `scenes.length`）：没有镜头时禁用渲染按钮。 */
  sceneCount: number
}>()

const currentJobId = ref<string | null>(null)

const { data: latestJob, isFetching: latestJobFetching } = useLatestJobQuery(
  () => props.projectId,
  RENDER_JOB_TYPE,
)
// 必须等这次挂载的请求结束再采用：切走再回来时 `data` 一上来就是缓存值（可能
// 是过期的旧任务，且和新结果一致时 watcher 看不到任何变化），不能直接用。
let latestJobAdopted = false
watch(
  [latestJob, latestJobFetching],
  ([value, fetching]) => {
    if (latestJobAdopted || value === undefined || fetching) return // still loading
    latestJobAdopted = true
    if (currentJobId.value === null && value !== null) currentJobId.value = value.id
  },
  { immediate: true },
)

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
  <div class="flex flex-col gap-2">
    <p
      v-if="project?.completed_at"
      class="text-xs text-emerald-700"
    >
      项目已完成
    </p>

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
        class="max-h-[60vh] w-full rounded bg-black"
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
