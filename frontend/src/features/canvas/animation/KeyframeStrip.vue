<script setup lang="ts">
/**
 * 预览关键帧条（任务 T12；画布布局优化重写）：显示选中镜头最近一次
 * `render_preview` 的关键帧（来自 `scene-checks` 读模型的 `images`），点击
 * 放大；放大后可用左右按钮或方向键在同一镜头的相邻关键帧间切换（到头尾
 * 停住）。没有图片时退回到 `keyframeHint.ts` 的一行文字提示。
 */
import { computed, ref } from 'vue'
import { ChevronLeftIcon, ChevronRightIcon } from '@lucide/vue'
import { useEventListener } from '@vueuse/core'
import { blobUrl } from '@/api/endpoints'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { keyframeHint } from './keyframeHint'
import { stepKeyframe } from './keyframeNav'

const props = defineProps<{
  projectId: string
  sceneId: string | null
  /** 关键帧 blob sha256，按渲染顺序。 */
  images: readonly string[]
  /** 预览之后镜头代码又改过。 */
  stale: boolean
}>()

const urls = computed(() => props.images.map((sha) => blobUrl(props.projectId, sha)))
const hint = computed(() => keyframeHint(props.sceneId))
const openIndex = ref<number | null>(null)
const dialogOpen = computed({
  get: () => openIndex.value !== null,
  set: (open) => {
    if (!open) openIndex.value = null
  },
})

function step(delta: 1 | -1): void {
  if (openIndex.value === null) return
  openIndex.value = stepKeyframe(openIndex.value, delta, urls.value.length)
}

// 监听 window 而不是弹窗内容：点到头尾被禁用的按钮后焦点会掉到 body，
// 绑在内容上的 keydown 就收不到了。
useEventListener(window, 'keydown', onKeydown)

function onKeydown(event: KeyboardEvent): void {
  if (openIndex.value === null) return
  if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
  else return
  event.preventDefault()
}
</script>

<template>
  <div
    v-if="urls.length"
    class="flex flex-col gap-1"
    data-testid="keyframe-strip"
  >
    <p
      v-if="stale"
      class="text-xs text-amber-600"
    >
      代码在预览后改过，这些关键帧可能已过期
    </p>
    <div class="flex gap-2 overflow-x-auto pb-1">
      <button
        v-for="(url, index) in urls"
        :key="url"
        type="button"
        class="bg-muted h-20 shrink-0 overflow-hidden rounded border"
        :aria-label="`放大关键帧 ${index + 1}`"
        @click="openIndex = index"
      >
        <img
          :src="url"
          :alt="`${sceneId} 关键帧 ${index + 1}`"
          class="h-full w-auto object-contain"
          loading="lazy"
        >
      </button>
    </div>

    <Dialog v-model:open="dialogOpen">
      <DialogContent class="max-w-4xl">
        <DialogTitle>{{ sceneId }} · 关键帧 {{ (openIndex ?? 0) + 1 }} / {{ urls.length }}</DialogTitle>
        <DialogDescription class="sr-only">
          预览关键帧大图
        </DialogDescription>
        <div
          v-if="openIndex !== null"
          class="relative"
        >
          <img
            :src="urls[openIndex]"
            :alt="`${sceneId} 关键帧 ${openIndex + 1}`"
            class="w-full rounded"
          >
          <button
            type="button"
            class="absolute top-1/2 left-2 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 disabled:opacity-30"
            aria-label="上一张"
            :disabled="openIndex === 0"
            @click="step(-1)"
          >
            <ChevronLeftIcon class="size-5" />
          </button>
          <button
            type="button"
            class="absolute top-1/2 right-2 flex size-9 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 disabled:opacity-30"
            aria-label="下一张"
            :disabled="openIndex === urls.length - 1"
            @click="step(1)"
          >
            <ChevronRightIcon class="size-5" />
          </button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
  <p
    v-else
    class="text-muted-foreground truncate text-xs"
    :title="hint"
  >
    {{ hint }}
  </p>
</template>
