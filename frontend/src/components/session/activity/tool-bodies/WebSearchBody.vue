<script setup lang="ts">
/** `web-search`：解析成结果卡片；解析不了回退原始文本。 */
import { computed } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import { isHttpUrl, parseWebSearch } from '@/components/session/webSearchResult'
import ErrorPane from '@/components/session/activity/ErrorPane.vue'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem }>()

const ok = computed(() => (props.item.result && !props.item.result.isError ? props.item.result : null))
const parsed = computed(() => (ok.value ? parseWebSearch(ok.value.text) : null))
const query = computed(() => parsed.value?.query ?? (typeof props.item.args.query === 'string' ? props.item.args.query : ''))

function host(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return ''
  }
}
</script>

<template>
  <div class="space-y-2">
    <p
      v-if="query"
      class="text-muted-foreground text-xs"
    >
      查询：{{ query }}
    </p>
    <p
      v-if="!item.result"
      class="text-muted-foreground text-xs"
    >
      搜索中…
    </p>
    <template v-else-if="ok">
      <p
        v-if="parsed && parsed.hits.length === 0"
        class="text-muted-foreground text-xs"
      >
        没有找到结果
      </p>
      <ul
        v-else-if="parsed"
        class="space-y-2"
      >
        <li
          v-for="(hit, index) in parsed.hits"
          :key="index"
          data-testid="search-hit"
          class="bg-muted/30 rounded-lg border p-3 text-sm"
        >
          <a
            v-if="isHttpUrl(hit.url)"
            :href="hit.url"
            target="_blank"
            rel="noopener noreferrer"
            class="font-medium underline-offset-2 hover:underline"
          >{{ hit.title }}</a>
          <span
            v-else
            class="font-medium"
          >{{ hit.title }}</span>
          <div class="text-muted-foreground text-xs">
            {{ host(hit.url) }}<template v-if="hit.published">
              · {{ hit.published }}
            </template>
          </div>
          <p
            v-if="hit.snippet"
            class="text-muted-foreground mt-1 text-xs"
          >
            {{ hit.snippet }}
          </p>
        </li>
      </ul>
      <ToolPane
        v-else
        title="结果"
        :copy-text="ok.text"
      >
        <pre class="p-3 font-mono whitespace-pre-wrap">{{ ok.text || '（无输出）' }}</pre>
      </ToolPane>
    </template>
    <ErrorPane :item="item" />
  </div>
</template>
