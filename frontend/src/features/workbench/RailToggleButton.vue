<script setup lang="ts">
/**
 * 画布右上角的快照栏开关（紧挨在渲染/编辑切换右边）。快照栏默认整栏隐藏，这里是展开入口；
 * 展开后仍可从这里收起。样式和 `EditModeToggle` 的分段按钮同尺寸，视觉上并排成一组。
 */
import { HistoryIcon } from '@lucide/vue'

defineProps<{ collapsed: boolean }>()
defineEmits<{ (e: 'toggle'): void }>()
</script>

<template>
  <button
    type="button"
    class="flex size-7 shrink-0 items-center justify-center rounded-md border"
    :class="collapsed ? 'hover:bg-muted' : 'bg-primary/10 text-primary'"
    :title="collapsed ? '展开快照栏' : '收起快照栏'"
    :aria-label="collapsed ? '展开快照栏' : '收起快照栏'"
    :aria-pressed="!collapsed"
    data-testid="open-snapshots"
    @click="$emit('toggle')"
  >
    <HistoryIcon class="size-3.5" />
  </button>
</template>
