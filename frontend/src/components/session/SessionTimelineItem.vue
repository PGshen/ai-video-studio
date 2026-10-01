<script setup lang="ts">
/**
 * 时间线里「非活动」条目的渲染：用户消息/助手文本用 @ai-elements 的 Message，
 * notice/error/snapshot/suggestion 用简单的提示条。思考和工具调用由 `SessionTimeline` 归成
 * 活动组渲染（`activity/`），不会到这里。
 */
import { Message, MessageContent } from '@/components/ai-elements/message'
import type { PlainItem } from './groupTimeline'
import { noticeText } from './noticeText'
import SuggestionCard from './SuggestionCard.vue'
import { snapshotEventLabel } from './snapshotReason'

defineProps<{ item: PlainItem; projectId: string | null }>()
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

  <SuggestionCard
    v-else-if="item.kind === 'suggestion' && projectId !== null"
    :item="item"
    :project-id="projectId"
  />

  <div
    v-else-if="item.kind === 'notice'"
    class="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900"
  >
    {{ noticeText(item.noticeKind, item.message) }}
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
