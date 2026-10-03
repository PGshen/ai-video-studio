<script setup lang="ts">
/**
 * 预览关键帧条（任务 T12；画布布局优化重写）：显示选中镜头最近一次
 * `render_preview` 的关键帧（来自 `scene-checks` 读模型的 `images`），点击
 * 放大。没有图片时退回到 `keyframeHint.ts` 的一行文字提示。
 */
import { computed, ref } from 'vue'
import { blobUrl } from '@/api/endpoints'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { keyframeHint } from './keyframeHint'

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
</script>

<template>
  <div
    v-if="urls.length"
    class="flex flex-col gap-1"
    data-testid="keyframe-strip"
  >
    <p class="text-muted-foreground text-xs">
      预览关键帧
      <span
        v-if="stale"
        class="text-amber-600"
      >（代码在预览后改过，可能已过期）</span>
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
        <img
          v-if="openIndex !== null"
          :src="urls[openIndex]"
          :alt="`${sceneId} 关键帧 ${openIndex + 1}`"
          class="w-full rounded"
        >
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
