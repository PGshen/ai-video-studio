<script setup lang="ts">
/**
 * 叙事镜头卡片列表（M3 T10）：纯展示。每张卡片显示镜头 id、旁白摘要、
 * beat 数，以及校验标记（有问题时标红）和配音状态（已配音/未配音/配音已过期）；
 * 整体播放时选中项跟随当前镜头（由画布同步 `selectedId`），并自动滚动到它。
 * 状态计算在 `narrativeDoc.ts`/`timingStatus.ts`，这里只渲染。
 */
import { nextTick, onMounted, ref, watch } from 'vue'
import type { NarrativeScene } from './narrativeDoc'
import type { DubbingState, SceneDubbing } from './timingStatus'

const DUBBING_LABELS: Record<DubbingState, string> = {
  missing: '未配音',
  dubbed: '已配音',
  stale: '配音已过期',
}

const props = defineProps<{
  scenes: NarrativeScene[]
  issues: Record<string, string[]>
  dubbing: Record<string, SceneDubbing>
  selectedId: string | null
  /** 整体播放中正在播（或暂停所在）的镜头；没有在播时为 null。 */
  playingId?: string | null
}>()

const emit = defineEmits<{ (e: 'select', id: string): void }>()

// 整体播放切到下一个镜头时，把它滚进可视区（nearest：已经可见就不动）。
const cards = ref<Record<string, HTMLElement>>({})
async function scrollToPlaying(): Promise<void> {
  if (!props.playingId) return
  await nextTick()
  cards.value[props.playingId]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}
watch(() => props.playingId, scrollToPlaying)
onMounted(scrollToPlaying)
</script>

<template>
  <div class="flex min-h-0 flex-col gap-1 overflow-y-auto text-sm">
    <ul class="flex flex-col gap-1">
      <li
        v-for="scene in scenes"
        :key="scene.id"
      >
        <button
          :ref="(el) => { if (el) cards[scene.id] = el as HTMLElement }"
          type="button"
          class="flex w-full flex-col gap-1 rounded border px-2 py-1.5 text-left"
          :class="scene.id === selectedId ? 'border-primary bg-primary/10' : 'hover:bg-muted'"
          :data-playing="scene.id === playingId ? 'true' : undefined"
          @click="emit('select', scene.id)"
        >
          <span class="flex items-center justify-between gap-2">
            <span class="truncate font-medium">{{ scene.id }}</span>
            <span class="flex shrink-0 items-center gap-1">
              <span
                v-if="(issues[scene.id] ?? []).length > 0"
                class="bg-destructive/10 text-destructive rounded px-1.5 py-0.5 text-xs"
              >
                {{ issues[scene.id]!.length }} 个问题
              </span>
              <span
                v-else
                class="rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-800"
              >
                校验通过
              </span>
              <span
                class="rounded px-1.5 py-0.5 text-xs"
                :class="dubbing[scene.id]?.state === 'dubbed' ? 'bg-sky-100 text-sky-800' : 'bg-amber-100 text-amber-800'"
              >
                {{ DUBBING_LABELS[dubbing[scene.id]?.state ?? 'missing'] }}
              </span>
            </span>
          </span>
          <span class="text-muted-foreground line-clamp-2 text-xs">
            {{ scene.narration || '（旁白为空）' }}
          </span>
          <span class="text-muted-foreground text-xs">{{ scene.beats.length }} 个 beat</span>
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
