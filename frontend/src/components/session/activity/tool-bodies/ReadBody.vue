<script setup lang="ts">
/** `read`：文件路径做标题栏、语言按扩展名；Claude 的行号前缀去掉后交给代码块自己编号。 */
import { computed } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import { codeLanguage } from '@/components/session/codeLanguage'
import { parseNumberedLines } from '@/components/session/readResult'
import type { ToolView } from '@/components/session/toolPresentation'
import CodeView from '@/components/session/activity/CodeView.vue'
import ErrorPane from '@/components/session/activity/ErrorPane.vue'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem; view: ToolView }>()

const title = computed(() => props.view.path ?? props.view.summary)
const language = computed(() => codeLanguage(props.view.path))
const range = computed(() => {
  const parts: string[] = []
  if (typeof props.item.args.offset === 'number') parts.push(`offset ${props.item.args.offset}`)
  if (typeof props.item.args.limit === 'number') parts.push(`limit ${props.item.args.limit}`)
  return parts.join(' · ')
})

const ok = computed(() => (props.item.result && !props.item.result.isError ? props.item.result : null))
const numbered = computed(() => (ok.value ? parseNumberedLines(ok.value.text) : null))
/** 带 offset 的结果行号不从 1 开始，代码块的行号对不上，保留原文逐行显示。 */
const keepOriginal = computed(() => numbered.value !== null && numbered.value.startLine !== 1)
const code = computed(() => (numbered.value && !keepOriginal.value ? numbered.value.code : (ok.value?.text ?? '')))
</script>

<template>
  <div class="space-y-2">
    <p
      v-if="range"
      class="text-muted-foreground text-xs"
    >
      {{ range }}
    </p>
    <ToolPane
      v-if="ok"
      :title="title"
      :language="language"
      :copy-text="code"
    >
      <p
        v-if="code.trim() === ''"
        class="text-muted-foreground p-3"
      >
        （无输出）
      </p>
      <pre
        v-else-if="keepOriginal"
        class="p-3 font-mono whitespace-pre-wrap"
      >{{ ok.text }}</pre>
      <CodeView
        v-else
        :code="code"
        :language="language"
        line-numbers
      />
    </ToolPane>
    <p
      v-else-if="!item.result"
      class="text-muted-foreground text-xs"
    >
      读取中…
    </p>
    <ErrorPane :item="item" />
    <p
      v-if="ok?.truncated"
      class="text-muted-foreground text-xs"
    >
      结果已截断
    </p>
  </div>
</template>
