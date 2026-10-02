<script setup lang="ts">
/** 工具失败时的统一错误面板；没有失败就什么都不渲染。由各正文自己放置，避免重复。 */
import type { ToolCallItem } from '@/composables/useSessionStream'
import ToolPane from './ToolPane.vue'

defineProps<{ item: ToolCallItem }>()
</script>

<template>
  <ToolPane
    v-if="item.result?.isError"
    title="错误"
    tone="error"
    :copy-text="item.result.text"
  >
    <pre class="p-3 font-mono whitespace-pre-wrap">{{ item.result.text || '（无输出）' }}</pre>
  </ToolPane>
</template>
