<script setup lang="ts">
/**
 * 风格编辑态右侧的 AI 对话区（计划 style-library T10）：会话选择 + 消息流 + 输入框，复用
 * `components/session/`（项目工作台、头脑风暴同一套）。会话属于这套风格（范围 `style`），没有项目；
 * AI 改的是服务端草稿，`useSessionStream` 在 `workspace_changed` 和轮次开始/结束时刷新草稿。
 * `beforeSend`：发送前先把编辑器里还没写出的编辑写进草稿（否则轮次开始后写入会被 409 拒绝）。
 */
import { useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import SessionPanel from '@/components/session/SessionPanel.vue'
import SessionPicker from '@/components/session/SessionPicker.vue'
import { useEnsureSession } from '@/components/session/useEnsureSession'
import { queryKeys } from '@/composables/queries'
import { styleScope } from '@/composables/sessionScope'

const props = defineProps<{
  styleId: string
  beforeSend?: () => Promise<void>
}>()
const emit = defineEmits<{
  /** 点发送起（`true`）到服务端状态接管（`false`）：编辑区据此本地只读，避免这段时间敲的字被 409 丢弃。 */
  (e: 'sending', value: boolean): void
}>()

const scope = computed(() => styleScope(props.styleId))
const sessionId = ref<string | null>(null)
// 换一套风格：上一套风格的会话不能带过来。
watch(
  () => props.styleId,
  () => {
    sessionId.value = null
  },
)
const createSession = useEnsureSession(scope, sessionId)

const queryClient = useQueryClient()
/** 发送成功后正在重取的草稿状态；`sending(false)` 要等它完成（此时 `busy` 已由服务端给出）。 */
let refetch: Promise<unknown> | null = null
/** 一轮已被后端接受（新消息或 [继续]）：这套风格此刻已经 busy。新会话的第一轮时 SSE 可能还没连上，收不到
 * `turn_status`，所以发送成功后主动刷新一次草稿状态，编辑区才会立刻只读。 */
function onAccepted(): void {
  refetch = queryClient.invalidateQueries({ queryKey: queryKeys.styleDraft(props.styleId) })
}

async function onSending(value: boolean): Promise<void> {
  if (value) {
    emit('sending', true)
    return
  }
  const pending = refetch
  refetch = null
  // 重取失败也要解锁：此后编辑区只读与否由服务端的 `busy` 决定。
  if (pending) await pending.catch(() => undefined)
  emit('sending', false)
}
</script>

<template>
  <aside
    class="flex min-h-0 flex-col gap-2 rounded-md border p-3"
    data-testid="style-chat"
  >
    <h3 class="text-sm font-medium">
      AI 对话
    </h3>
    <p class="text-muted-foreground text-xs">
      告诉 AI 想怎么改这套风格；改动会出现在左边的草稿里，满意了再点「保存」。
    </p>
    <SessionPicker
      v-model:session-id="sessionId"
      :scope="scope"
    />
    <SessionPanel
      :session-id="sessionId"
      :project-id="null"
      :create-session="createSession"
      :before-send="beforeSend"
      @accepted="onAccepted"
      @sending="onSending"
    />
  </aside>
</template>
