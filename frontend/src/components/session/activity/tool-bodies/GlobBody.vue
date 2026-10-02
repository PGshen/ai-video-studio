<script setup lang="ts">
/** `glob`：`Glob` / `list_files` 的结果逐行成列表，工作区绝对前缀去掉。 */
import { computed } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import { relativizePath, type ToolView } from '@/components/session/toolPresentation'
import ErrorPane from '@/components/session/activity/ErrorPane.vue'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem; view: ToolView }>()

const ok = computed(() => (props.item.result && !props.item.result.isError ? props.item.result : null))
const entries = computed(() =>
  (ok.value?.text ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
    .map((line) => relativizePath(line)),
)
</script>

<template>
  <div class="space-y-2">
    <ToolPane
      v-if="ok"
      :title="view.summary"
      :copy-text="entries.join('\n')"
    >
      <p
        v-if="entries.length === 0"
        class="text-muted-foreground p-3"
      >
        （无匹配）
      </p>
      <ul
        v-else
        class="p-3 font-mono"
      >
        <li
          v-for="(entry, index) in entries"
          :key="index"
          data-testid="glob-entry"
        >
          {{ entry }}
        </li>
      </ul>
    </ToolPane>
    <p
      v-else-if="!item.result"
      class="text-muted-foreground text-xs"
    >
      查找中…
    </p>
    <ErrorPane :item="item" />
  </div>
</template>
