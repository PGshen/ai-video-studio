<script setup lang="ts">
/**
 * 叙事镜头卡片列表（M3 T10）：纯展示。每张卡片显示镜头 id、旁白摘要、
 * beat 数，以及校验标记（有问题时标红）和配音状态（已配音/未配音）。
 * 状态计算在 `narrativeDoc.ts`/`timingStatus.ts`，这里只渲染。
 */
import type { NarrativeScene } from './narrativeDoc'
import type { SceneDubbing } from './timingStatus'

defineProps<{
  scenes: NarrativeScene[]
  issues: Record<string, string[]>
  dubbing: Record<string, SceneDubbing>
  selectedId: string | null
}>()

const emit = defineEmits<{ (e: 'select', id: string): void }>()
</script>

<template>
  <div class="flex min-h-0 flex-col gap-1 overflow-y-auto text-sm">
    <ul class="flex flex-col gap-1">
      <li
        v-for="scene in scenes"
        :key="scene.id"
      >
        <button
          type="button"
          class="flex w-full flex-col gap-1 rounded border px-2 py-1.5 text-left"
          :class="scene.id === selectedId ? 'border-primary bg-primary/10' : 'hover:bg-muted'"
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
                {{ dubbing[scene.id]?.state === 'dubbed' ? '已配音' : '未配音' }}
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
