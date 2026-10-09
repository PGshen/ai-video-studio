<script setup lang="ts">
/**
 * 消息流 + 输入框（任务简报 T13，控制者裁定 2/3）。会话状态来自
 * `useSessionStream`（T12）；发送用乐观插入（`addLocalUserMessage`）避免
 * 等 SSE 回放才看到自己刚发的消息；[停止]/[继续] 的可用性由纯函数
 * `computeTurnControls` 决定。
 */
import { computed, nextTick, ref, toRef } from 'vue'
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
  type AttachmentFile,
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
import PromptPrefill from './PromptPrefill.vue'
import AttachButton from './AttachButton.vue'
import AttachmentChips from './AttachmentChips.vue'
import {
  type AttachmentAccept,
  acceptAttribute,
  classifyFile,
  validateAttachments,
} from './attachmentRules'
import SessionTimeline from './SessionTimeline.vue'

/**
 * `projectId` 只用于工具结果图片的地址；头脑风暴会话没有项目，传 `null`。`prefill`（M5 T13）：
 * 往输入框预填文本（处理回退建议时用），`key` 变化才写入；消息发送成功后发出 `sent`。
 * `createSession`：没有会话时第一次发送先用它建会话（它要把新会话 id 写回父组件的 `sessionId`）；
 * 不传则没有会话时输入框禁用。`beforeSend`：发送前的准备（风格编辑用它把还没写出的编辑写进草稿）。
 */
const props = defineProps<{
  sessionId: string | null
  projectId: string | null
  prefill?: { text: string; key: string } | null
  createSession?: () => Promise<string>
  /** 每次发送（含「继续」）之前先执行；失败（reject）则不发送，错误显示在输入框上方。 */
  beforeSend?: () => Promise<void>
  /** 能上传哪些附件：默认图片和文件都行；选题对话没有工作区，只收图片（设计 2026-10-09）。 */
  attachmentAccept?: AttachmentAccept
}>()

const accept = computed<AttachmentAccept>(() => props.attachmentAccept ?? 'all')
const emit = defineEmits<{
  /** 用户发的新消息已被后端接收（[继续] 不发：它没有把输入框里的内容发出去）。 */
  (e: 'sent'): void
  /** 后端接受了一轮（新消息或 [继续]）：这一轮此刻已排队或运行。 */
  (e: 'accepted'): void
  /** 一次发送/继续开始（`true`，在 `beforeSend` 之前）和结束（`false`，无论成败）；
   * 风格编辑据此在这段时间内本地锁住编辑区。 */
  (e: 'sending', value: boolean): void
}>()

const sessionIdRef = toRef(props, 'sessionId')
const { items, turnStatus, turns, addLocalUserMessage, markTurnAccepted, removeLocalUserMessage } =
  useSessionStream(sessionIdRef)

/** 正在排队/运行的 turn：活动组据此决定展开与转圈。 */
const runningTurnId = computed(() => {
  const status = turnStatus.value
  return status && (status.status === 'queued' || status.status === 'running') ? status.turnId : null
})

const controls = computed(() =>
  computeTurnControls(turnStatus.value?.status ?? null, turnStatus.value?.neverStarted ?? false),
)

const sendMutation = useSendMessageMutation(() => props.sessionId ?? '')
const cancelMutation = useCancelSessionMutation(() => props.sessionId ?? '')
const continueMutation = useContinueSessionMutation(() => props.sessionId ?? '')

const sendError = ref<string | null>(null)
/** 正在为第一条消息建会话：期间不能再发，免得建出两个会话。 */
const creatingSession = ref(false)

const inputDisabled = computed(
  () =>
    (!props.sessionId && !props.createSession) || creatingSession.value || controls.value.inputDisabled,
)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && typeof error.detail !== 'string') return '会话忙，请等待当前一轮结束'
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

const optimisticMessages = { add: addLocalUserMessage, remove: removeLocalUserMessage }

/**
 * 带附件的发送失败时向 `PromptInput` 抛出：它据此保留附件（并恢复文字），错误已经显示在
 * `sendError` 里。不带附件时照旧吞掉错误（行为不变）。
 */
async function onSubmit(message: PromptInputMessage): Promise<void> {
  const text = message.text.trim()
  const files = (message.files as AttachmentFile[]).flatMap((item) => (item.file ? [item.file] : []))
  if ((!text && files.length === 0) || (!props.sessionId && !props.createSession)) return
  const problem = validateAttachments(files, accept.value)
  if (problem) {
    sendError.value = problem
    throw new Error(problem)
  }
  sendError.value = null
  emit('sending', true)
  try {
    await props.beforeSend?.()
    if (!props.sessionId && props.createSession) {
      creatingSession.value = true
      try {
        await props.createSession()
        // 等新会话 id 流到本组件的 props、`useSessionStream` 切到新会话（它会清空占位）之后，
        // 再乐观插入和发送；否则占位会被切换清掉，发送也会用到旧的空 id。
        await nextTick()
      } finally {
        creatingSession.value = false
      }
    }
    const previews = (message.files as AttachmentFile[]).flatMap((item) =>
      {
        if (!item.file) return []
        const kind = classifyFile(item.file, accept.value).kind
        const base = { kind, name: item.file.name, size: item.file.size }
        // 只有图片要缩略图；文件的 data URL 可能有几十 MB，不留在消息里。
        return [kind === 'image' ? { ...base, previewUrl: item.url } : base]
      },
    )
    await optimisticSend(
      optimisticMessages,
      text,
      async () => {
        const accepted = await sendMutation.mutateAsync(files.length ? { text, files } : { text })
        markTurnAccepted(accepted.turn_id, text)
      },
      previews,
    )
    emit('sent')
    emit('accepted')
  } catch (error) {
    sendError.value = describeError(error)
    if (files.length) throw error
  } finally {
    emit('sending', false)
  }
}

/** `PromptInput` 添加附件时的拦截（类型不符等）；提交失败已经在 `onSubmit` 里处理过。 */
function onInputError(error: { code: string; message: string }): void {
  if (error.code === 'submit_error') return
  sendError.value = error.code === 'accept' && accept.value === 'images' ? '选题对话只支持图片' : error.message
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
  emit('sending', true)
  try {
    await props.beforeSend?.()
    // The backend sends the fixed text "继续" as this turn's user message, or re-sends the
    // original message when the last turn never started (TD-19).
    const state = turnStatus.value
    const text = state?.neverStarted && state.userMessage ? state.userMessage : CONTINUE_TEXT
    await optimisticSend(optimisticMessages, text, async () => {
      const accepted = await continueMutation.mutateAsync()
      markTurnAccepted(accepted.turn_id, text)
    })
    emit('accepted')
  } catch (error) {
    sendError.value = describeError(error)
  } finally {
    emit('sending', false)
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
        <SessionTimeline
          :items="items"
          :running-turn-id="runningTurnId"
          :turns="turns"
          :project-id="props.projectId"
          :session-id="props.sessionId"
        />
      </ConversationContent>
    </Conversation>

    <p
      v-if="turnStatus?.error && turnStatus.neverStarted"
      class="text-muted-foreground text-sm"
    >
      {{ turnStatus.error }}
    </p>
    <p
      v-else-if="turnStatus?.error"
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

    <PromptInput
      :accept="acceptAttribute(accept)"
      multiple
      @submit="onSubmit"
      @error="onInputError"
    >
      <PromptPrefill :prefill="prefill" />
      <AttachmentChips :accept="accept" />
      <PromptInputBody>
        <PromptInputTextarea :disabled="inputDisabled" />
      </PromptInputBody>
      <PromptInputFooter>
        <div class="flex min-w-0 items-center">
          <AttachButton
            :disabled="inputDisabled"
            :label="accept === 'images' ? '添加图片' : '添加图片或文件'"
          />
          <slot name="tools" />
        </div>
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
            {{ controls.continueLabel }}
          </Button>
          <PromptInputSubmit :disabled="inputDisabled" />
        </div>
      </PromptInputFooter>
    </PromptInput>
  </div>
</template>
