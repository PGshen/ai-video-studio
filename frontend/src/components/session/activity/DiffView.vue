<script setup lang="ts">
/** 差异文本：按行首字符着色（`+` 新增、`-` 删除、`@@` hunk，其余是上下文）。 */
import { computed } from 'vue'

const props = defineProps<{ text: string }>()

const lines = computed(() =>
  props.text.split('\n').map((line) => ({
    line,
    kind: line.startsWith('@@')
      ? 'hunk'
      : line.startsWith('+')
        ? 'add'
        : line.startsWith('-')
          ? 'del'
          : 'ctx',
  })),
)

const CLASSES: Record<string, string> = {
  add: 'bg-green-500/10 text-green-700 dark:text-green-400',
  del: 'bg-red-500/10 text-red-700 dark:text-red-400',
  hunk: 'text-muted-foreground',
  ctx: '',
}
</script>

<template>
  <pre class="p-3 font-mono"><div
    v-for="(entry, index) in lines"
    :key="index"
    :data-diff="entry.kind"
    class="whitespace-pre-wrap"
    :class="CLASSES[entry.kind]"
  >{{ entry.line }}</div></pre>
</template>
