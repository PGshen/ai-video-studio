<script setup lang="ts">
/** `web-fetch`：可点击的 URL（仅 http(s)）+ 正文文本。 */
import { computed } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import type { ToolView } from '@/components/session/toolPresentation'
import { isHttpUrl } from '@/components/session/webSearchResult'
import ErrorPane from '@/components/session/activity/ErrorPane.vue'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem; view: ToolView }>()

const url = computed(() => (typeof props.item.args.url === 'string' ? props.item.args.url.trim() : ''))
const ok = computed(() => (props.item.result && !props.item.result.isError ? props.item.result : null))
</script>

<template>
  <div class="space-y-2">
    <p class="text-xs">
      <a
        v-if="isHttpUrl(url)"
        :href="url"
        target="_blank"
        rel="noopener noreferrer"
        class="text-muted-foreground break-all underline-offset-2 hover:underline"
      >{{ url }}</a>
      <span
        v-else
        class="text-muted-foreground break-all"
      >{{ url }}</span>
    </p>
    <ToolPane
      v-if="ok"
      :title="view.summary"
      :copy-text="ok.text"
    >
      <pre class="p-3 font-mono whitespace-pre-wrap">{{ ok.text || '（无输出）' }}</pre>
    </ToolPane>
    <p
      v-else-if="!item.result"
      class="text-muted-foreground text-xs"
    >
      读取中…
    </p>
    <ErrorPane :item="item" />
  </div>
</template>
