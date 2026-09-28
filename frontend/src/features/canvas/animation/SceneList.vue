<script setup lang="ts">
/**
 * 镜头列表（任务 T12）：纯展示组件，状态计算交给 `sceneStatus.ts`。
 * M2 只区分"已有代码"/"还没有代码"两种状态（决策记录 D38，"已校验/
 * 已过期"的持久化状态跟踪留给以后）。
 */
import type { SceneStatus } from './sceneStatus'

defineProps<{
  scenes: SceneStatus[]
  selectedId: string | null
}>()

const emit = defineEmits<{ (e: 'select', id: string): void }>()
</script>

<template>
  <div class="flex min-h-0 flex-col gap-1 overflow-y-auto text-sm">
    <p class="text-muted-foreground mb-1 text-xs font-medium">
      镜头
    </p>
    <ul>
      <li
        v-for="scene in scenes"
        :key="scene.id"
      >
        <button
          type="button"
          class="flex w-full items-center justify-between gap-2 truncate rounded px-2 py-1 text-left"
          :class="scene.id === selectedId ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
          @click="emit('select', scene.id)"
        >
          <span class="truncate">{{ scene.id }}</span>
          <span
            class="shrink-0 rounded px-1.5 py-0.5 text-xs"
            :class="scene.exists ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'"
          >
            {{ scene.exists ? '已有代码' : '待编写' }}
          </span>
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
