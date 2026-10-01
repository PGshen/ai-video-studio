<script setup lang="ts">
/** 通用工具正文（设计 §5 `generic`）：参数 JSON + 结果文本 + 结果图片缩略图。 */
import { computed } from 'vue'
import { blobUrl } from '@/api/endpoints'
import type { ToolCallItem } from '@/composables/useSessionStream'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem; projectId: string | null }>()

const argsText = computed(() => JSON.stringify(props.item.args, null, 2))
const images = computed(() => props.item.result?.images ?? [])
</script>

<template>
  <div class="space-y-2">
    <ToolPane
      title="参数"
      language="json"
      :copy-text="argsText"
    >
      <pre class="p-3 font-mono whitespace-pre-wrap">{{ argsText }}</pre>
    </ToolPane>
    <ToolPane
      v-if="item.result"
      :title="item.result.isError ? '错误' : '结果'"
      :tone="item.result.isError ? 'error' : 'default'"
      :copy-text="item.result.text"
    >
      <pre class="p-3 font-mono whitespace-pre-wrap">{{ item.result.text || '（无输出）' }}</pre>
    </ToolPane>
    <p
      v-if="item.result?.truncated"
      class="text-muted-foreground text-xs"
    >
      结果已截断
    </p>
    <div
      v-if="projectId !== null && images.length > 0"
      class="flex flex-wrap gap-2"
    >
      <img
        v-for="(image, index) in images"
        :key="image.sha256"
        :src="blobUrl(projectId, image.sha256)"
        :alt="`关键帧 ${index + 1}`"
        class="h-24 w-auto rounded border object-contain"
      >
    </div>
  </div>
</template>
