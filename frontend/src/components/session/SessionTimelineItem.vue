<script setup lang="ts">
/**
 * 时间线里「非活动」条目的渲染：用户消息/助手文本用 @ai-elements 的 Message，
 * notice/error/snapshot/suggestion 用简单的提示条。思考和工具调用由 `SessionTimeline` 归成
 * 活动组渲染（`activity/`），不会到这里。助手文本经 `SafeMarkdown` 渲染 Markdown（原始 HTML 转义 + 渲染层拦截）。
 */
import { computed } from 'vue'
import { CheckIcon, CopyIcon } from '@lucide/vue'
import { Message, MessageContent } from '@/components/ai-elements/message'
import type { TurnOut } from '@/types/api'
import { useCopy } from './activity/useCopy'
import type { PlainItem } from './groupTimeline'
import { noticeText } from './noticeText'
import SafeMarkdown from './SafeMarkdown.vue'
import SuggestionCard from './SuggestionCard.vue'
import { snapshotEventLabel } from './snapshotReason'
import { formatClock } from './turnMeta'

const props = defineProps<{
  item: PlainItem
  projectId: string | null
  turns?: ReadonlyMap<string, TurnOut>
}>()

const { copied, copy } = useCopy()

/** 用户气泡下的时间：优先用 turn 的创建时间，其次是乐观占位的发送时间；都没有就不显示。 */
const userTime = computed(() => {
  if (props.item.kind !== 'user_message') return ''
  return formatClock(props.turns?.get(props.item.turnId)?.created_at ?? props.item.at ?? '')
})
</script>

<template>
  <div
    v-if="item.kind === 'user_message'"
    class="flex flex-col items-end gap-1"
  >
    <Message from="user">
      <MessageContent>{{ item.text }}</MessageContent>
    </Message>
    <div class="text-muted-foreground flex items-center gap-3 text-xs">
      <span
        v-if="userTime"
        data-testid="user-time"
      >{{ userTime }}</span>
      <button
        type="button"
        class="hover:text-foreground"
        aria-label="复制消息"
        data-testid="user-copy"
        @click="copy(item.text)"
      >
        <CheckIcon
          v-if="copied"
          class="size-4"
        />
        <CopyIcon
          v-else
          class="size-4"
        />
      </button>
    </div>
  </div>

  <Message
    v-else-if="item.kind === 'text'"
    from="assistant"
    class="max-w-full"
  >
    <MessageContent class="w-full">
      <SafeMarkdown :content="item.text" />
      <span
        v-if="item.streaming"
        class="animate-pulse"
        data-testid="stream-cursor"
      >▍</span>
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
