<script setup lang="ts">
/**
 * 镜头列表（任务 T12；TD-33、画布布局优化扩展）：纯展示组件，状态计算交给
 * `sceneStatus.ts`。每个镜头是一张卡片：最近一次 `render_preview` 的第一张
 * 关键帧缩略图（没有就是占位）+ 镜头 id + 一排紧凑状态点（代码、校验、预览），
 * 悬停状态点看文字说明。`stale` 表示检查之后代码又改过。
 */
import { computed } from 'vue'
import { ImageIcon } from '@lucide/vue'
import { blobUrl } from '@/api/endpoints'
import type { SceneStatus } from './sceneStatus'
import { checkLabel, checkTone, type CheckTone } from './checkSummary'

const props = defineProps<{
  projectId: string
  scenes: SceneStatus[]
  selectedId: string | null
}>()

const emit = defineEmits<{ (e: 'select', id: string): void }>()

const TONE_CLASS: Record<CheckTone, string> = {
  none: 'bg-muted-foreground/30',
  passed: 'bg-emerald-500',
  stale: 'bg-amber-500',
  failed: 'bg-destructive',
}

interface Dot {
  key: string
  label: string
  tone: CheckTone
}

const rows = computed(() =>
  props.scenes.map((scene) => {
    const thumb = scene.renderPreview?.images[0]
    const dots: Dot[] = [
      { key: 'code', label: scene.exists ? '代码：已有' : '代码：待编写', tone: scene.exists ? 'passed' : 'none' },
      { key: 'validate', label: checkLabel('校验', scene.validateScenes), tone: checkTone(scene.validateScenes) },
      { key: 'preview', label: checkLabel('预览', scene.renderPreview), tone: checkTone(scene.renderPreview) },
    ]
    return {
      scene,
      thumbUrl: thumb === undefined ? null : blobUrl(props.projectId, thumb),
      dots,
    }
  }),
)
</script>

<template>
  <div class="flex min-h-0 flex-col gap-1 overflow-y-auto text-sm">
    <ul class="flex flex-col gap-2">
      <li
        v-for="row in rows"
        :key="row.scene.id"
      >
        <button
          type="button"
          class="flex w-full flex-col gap-1.5 rounded-md border p-1.5 text-left"
          :class="row.scene.id === selectedId ? 'border-primary bg-primary/5' : 'hover:bg-muted border-transparent'"
          :data-testid="`scene-card-${row.scene.id}`"
          @click="emit('select', row.scene.id)"
        >
          <div class="bg-muted aspect-video w-full overflow-hidden rounded">
            <img
              v-if="row.thumbUrl"
              :src="row.thumbUrl"
              :alt="`${row.scene.id} 预览`"
              class="size-full object-cover"
              loading="lazy"
            >
            <div
              v-else
              class="text-muted-foreground/60 flex size-full items-center justify-center"
            >
              <ImageIcon class="size-5" />
            </div>
          </div>
          <div class="flex items-center justify-between gap-2 px-0.5">
            <span class="truncate font-medium">{{ row.scene.id }}</span>
            <span class="flex shrink-0 items-center gap-1">
              <span
                v-for="dot in row.dots"
                :key="dot.key"
                class="size-2 rounded-full"
                :class="TONE_CLASS[dot.tone]"
                :title="dot.label"
                :aria-label="dot.label"
                role="img"
              />
            </span>
          </div>
        </button>
      </li>
      <li
        v-if="scenes.length === 0"
        class="text-muted-foreground px-2 py-1"
      >
        还没有镜头
      </li>
    </ul>
  </div>
</template>
