<script setup lang="ts">
/**
 * 消息流 + 输入框（任务简报 T13，控制者裁定 2/3）。会话状态来自
 * `useSessionStream`（T12）；发送用乐观插入（`addLocalUserMessage`）避免
 * 等 SSE 回放才看到自己刚发的消息；[停止]/[继续] 的可用性由纯函数
 * `computeTurnControls` 决定。
 */
import { computed, ref, toRef } from 'vue'
import { Button } from '@/components/ui/button'
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from '@/components/ai-elements/conversation'
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  type PromptInputMessage,
} from '@/components/ai-elements/prompt-input'
import { useSessionStream } from '@/composables/useSessionStream'
import {
  useCancelSessionMutation,
  useContinueSessionMutation,
  useSendMessageMutation,
} from '@/composables/queries'
import { ApiError } from '@/api/http'
import { computeTurnControls } from './turnControls'
import { CONTINUE_TEXT, optimisticSend } from './optimisticSend'
import SessionTimelineItem from './SessionTimelineItem.vue'

const props = defineProps<{ sessionId: string | null }>()

const sessionIdRef = toRef(props, 'sessionId')
const { items, turnStatus, addLocalUserMessage, removeLocalUserMessage } =
  useSessionStream(sessionIdRef)

const controls = computed(() => computeTurnControls(turnStatus.value?.status ?? null))

const sendMutation = useSendMessageMutation(() => props.sessionId ?? '')
const cancelMutation = useCancelSessionMutation(() => props.sessionId ?? '')
const continueMutation = useContinueSessionMutation(() => props.sessionId ?? '')

const sendError = ref<string | null>(null)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return '会话忙，请等待当前一轮结束'
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

const optimisticMessages = { add: addLocalUserMessage, remove: removeLocalUserMessage }

async function onSubmit(message: PromptInputMessage): Promise<void> {
  const text = message.text.trim()
  if (!text || !props.sessionId) return
  sendError.value = null
  try {
    await optimisticSend(optimisticMessages, text, () => sendMutation.mutateAsync({ text }))
  } catch (error) {
    sendError.value = describeError(error)
  }
}

async function onStop(): Promise<void> {
  try {
    await cancelMutation.mutateAsync()
  } catch (error) {
    sendError.value = describeError(error)
  }
}

async function onContinue(): Promise<void> {
  sendError.value = null
  try {
    // The backend sends the fixed text "继续" as this turn's user message.
    await optimisticSend(optimisticMessages, CONTINUE_TEXT, () => continueMutation.mutateAsync())
  } catch (error) {
    sendError.value = describeError(error)
  }
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-2">
    <Conversation class="min-h-0">
      <ConversationContent>
        <ConversationEmptyState
          v-if="items.length === 0"
          title="还没有消息"
          description="发一条消息开始对话"
        />
        <SessionTimelineItem
          v-for="(item, index) in items"
          :key="index"
          :item="item"
        />
      </ConversationContent>
    </Conversation>

    <p
      v-if="turnStatus?.error"
      class="text-destructive text-sm"
    >
      运行出错：{{ turnStatus.error }}
    </p>
    <p
      v-if="sendError"
      class="text-destructive text-sm"
    >
      {{ sendError }}
    </p>

    <PromptInput @submit="onSubmit">
      <PromptInputBody>
        <PromptInputTextarea :disabled="!sessionId || controls.inputDisabled" />
      </PromptInputBody>
      <PromptInputFooter>
        <div class="ml-auto flex items-center gap-2">
          <Button
            v-if="controls.showStop"
            type="button"
            variant="destructive"
            size="sm"
            @click="onStop"
          >
            停止
          </Button>
          <Button
            v-if="controls.showContinue"
            type="button"
            variant="outline"
            size="sm"
            @click="onContinue"
          >
            继续
          </Button>
          <PromptInputSubmit :disabled="!sessionId || controls.inputDisabled" />
        </div>
      </PromptInputFooter>
    </PromptInput>
  </div>
</template>
