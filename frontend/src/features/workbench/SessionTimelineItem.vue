<script setup lang="ts">
/**
 * 时间线单条渲染（从 `SessionPanel.vue` 拆出来，控制体积在简报建议的 250
 * 行以内）：用户消息/助手文本用 @ai-elements 的 Message，工具调用用 Tool
 * （可折叠，展示名字/参数/结果），notice/error/snapshot 用简单的提示条。
 */
import { computed } from 'vue'
import { blobUrl } from '@/api/endpoints'
import { Message, MessageContent } from '@/components/ai-elements/message'
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from '@/components/ai-elements/tool'
import type { TimelineItem } from '@/composables/useSessionStream'
import { snapshotEventLabel } from './snapshotReason'

const props = defineProps<{ item: TimelineItem; projectId: string }>()

const NOTICE_LABELS: Record<string, string> = {
  guard_restored: '越界写入已被还原',
  cost_unpriced: '本轮成本未计价（模型配置缺单价）',
}

const toolState = computed(() => {
  if (props.item.kind !== 'tool_call') return 'input-available' as const
  if (!props.item.result) return 'input-available' as const
  return props.item.result.isError ? ('output-error' as const) : ('output-available' as const)
})

/** 工具结果里的图片（TD-21 修复后）：每张图带 `sha256`，拼 blob 地址渲染真缩略图。 */
const images = computed(() => {
  if (props.item.kind !== 'tool_call') return []
  return props.item.result?.images ?? []
})
</script>

<template>
  <Message
    v-if="item.kind === 'user_message'"
    from="user"
  >
    <MessageContent>{{ item.text }}</MessageContent>
  </Message>

  <Message
    v-else-if="item.kind === 'text'"
    from="assistant"
  >
    <MessageContent :class="item.streaming ? 'opacity-70' : ''">
      {{ item.text }}
    </MessageContent>
  </Message>

  <Tool v-else-if="item.kind === 'tool_call'">
    <ToolHeader
      type="dynamic-tool"
      :tool-name="item.name"
      :state="toolState"
    />
    <ToolContent>
      <ToolInput :input="item.args" />
      <ToolOutput
        :output="item.result?.isError ? undefined : item.result?.text"
        :error-text="item.result?.isError ? item.result.text : undefined"
      />
      <div
        v-if="images.length > 0"
        class="flex flex-wrap gap-2 px-4 pb-4"
      >
        <img
          v-for="(image, index) in images"
          :key="image.sha256"
          :src="blobUrl(projectId, image.sha256)"
          :alt="`关键帧 ${index + 1}`"
          class="h-24 w-auto rounded border object-contain"
        >
      </div>
    </ToolContent>
  </Tool>

  <div
    v-else-if="item.kind === 'notice'"
    class="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900"
  >
    {{ NOTICE_LABELS[item.noticeKind] ?? item.noticeKind }}
    <span v-if="item.message">：{{ item.message }}</span>
    <span v-if="item.paths?.length">（{{ item.paths.join('、') }}）</span>
  </div>

  <div
    v-else-if="item.kind === 'error'"
    class="rounded-md border border-destructive bg-destructive/10 p-2 text-sm text-destructive"
  >
    出错：{{ item.message }}
  </div>

  <p
    v-else-if="item.kind === 'snapshot'"
    class="text-muted-foreground text-xs"
  >
    {{ snapshotEventLabel(item.reason, item.created) }}
  </p>
</template>
