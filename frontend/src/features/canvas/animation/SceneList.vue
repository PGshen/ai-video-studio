<script setup lang="ts">
/**
 * 镜头列表（任务 T12；TD-33 扩展）：纯展示组件，状态计算交给
 * `sceneStatus.ts`。"已有代码/还没有代码"（决策记录 D38）之外，现在还显示
 * 最近一次 `validate_scenes`/`render_preview` 的结果——`stale: true` 时用
 * "（已过期）"标出，提示代码在检查之后又改过。
 */
import type { SceneStatus } from './sceneStatus'
import type { SceneCheckOut } from '@/types/api'

defineProps<{
  scenes: SceneStatus[]
  selectedId: string | null
}>()

const emit = defineEmits<{ (e: 'select', id: string): void }>()

function checkLabel(prefix: string, check: SceneCheckOut | null): string | null {
  if (check === null || check.status === 'not_checked') return null
  const outcome = check.status === 'passed' ? '通过' : '失败'
  return `${prefix}${outcome}${check.stale ? '（已过期）' : ''}`
}
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
          class="flex w-full flex-col gap-0.5 truncate rounded px-2 py-1 text-left"
          :class="scene.id === selectedId ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
          @click="emit('select', scene.id)"
        >
          <span class="flex items-center justify-between gap-2">
            <span class="truncate">{{ scene.id }}</span>
            <span
              class="shrink-0 rounded px-1.5 py-0.5 text-xs"
              :class="scene.exists ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'"
            >
              {{ scene.exists ? '已有代码' : '待编写' }}
            </span>
          </span>
          <span
            v-if="checkLabel('校验', scene.validateScenes) || checkLabel('预览', scene.renderPreview)"
            class="text-muted-foreground truncate text-xs"
          >
            {{ [checkLabel('校验', scene.validateScenes), checkLabel('预览', scene.renderPreview)]
              .filter((label) => label !== null)
              .join(' · ') }}
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
