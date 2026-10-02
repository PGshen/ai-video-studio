<script setup lang="ts">
/** `grep`：搜索范围（路径 / glob）+ 保留换行的等宽结果。 */
import { computed } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import type { ToolView } from '@/components/session/toolPresentation'
import ErrorPane from '@/components/session/activity/ErrorPane.vue'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem; view: ToolView }>()

const ok = computed(() => (props.item.result && !props.item.result.isError ? props.item.result : null))
const scope = computed(() =>
  [props.item.args.path, props.item.args.glob]
    .filter((value): value is string => typeof value === 'string' && value !== '')
    .join(' · '),
)
</script>

<template>
  <div class="space-y-2">
    <p
      v-if="scope"
      class="text-muted-foreground text-xs"
    >
      {{ scope }}
    </p>
    <ToolPane
      v-if="ok"
      :title="view.summary"
      :copy-text="ok.text"
    >
      <p
        v-if="ok.text.trim() === ''"
        class="text-muted-foreground p-3"
      >
        （无匹配）
      </p>
      <pre
        v-else
        class="p-3 font-mono whitespace-pre-wrap"
      >{{ ok.text }}</pre>
    </ToolPane>
    <p
      v-else-if="!item.result"
      class="text-muted-foreground text-xs"
    >
      搜索中…
    </p>
    <ErrorPane :item="item" />
  </div>
</template>
