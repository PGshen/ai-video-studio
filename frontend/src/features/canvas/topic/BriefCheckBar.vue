<script setup lang="ts">
/**
 * 选题简报的检查提示条（计划 M4 T11）：显示 `check_brief` 同一份检查结果。
 * 只是提示，不禁用「定稿」按钮（计划 D4）。
 */
import { computed } from 'vue'
import type { TopicCheckOut } from '@/types/api'
import { computeBriefStatus } from './briefStatus'

const props = defineProps<{ check: TopicCheckOut | undefined }>()
const status = computed(() => computeBriefStatus(props.check))

const tone = computed(() => {
  switch (status.value.level) {
    case 'ok':
      return 'border-emerald-300 bg-emerald-50 text-emerald-900'
    case 'warnings':
      return 'border-amber-300 bg-amber-50 text-amber-900'
    case 'errors':
      return 'border-destructive bg-destructive/10'
    default:
      return 'bg-muted'
  }
})
</script>

<template>
  <div
    class="rounded border px-3 py-2 text-sm"
    :class="tone"
    data-testid="brief-check"
  >
    <p>{{ status.headline }}</p>
    <ul
      v-if="status.errors.length"
      class="mt-1 list-disc pl-5 text-xs"
    >
      <li
        v-for="message in status.errors"
        :key="message"
      >
        {{ message }}
      </li>
    </ul>
    <ul
      v-if="status.warnings.length"
      class="mt-1 list-disc pl-5 text-xs opacity-80"
    >
      <li
        v-for="message in status.warnings"
        :key="message"
      >
        警告：{{ message }}
      </li>
    </ul>
  </div>
</template>
