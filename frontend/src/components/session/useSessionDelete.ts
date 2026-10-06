/**
 * 删除会话的共用逻辑（会话切换气泡 `SessionSwitcher`、工作台左侧的 `SessionList`）：
 * 行内二次确认的状态、调用删除接口、删掉当前会话后切到剩下的会话。
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { ApiError } from '@/api/http'
import { useDeleteSessionMutation, useSessionsQuery } from '@/composables/queries'
import type { SessionScope } from '@/composables/sessionScope'

export function useSessionDelete(
  scope: ComputedRef<SessionScope>,
  sessionId: Ref<string | null>,
) {
  const { data: sessions } = useSessionsQuery(() => scope.value)
  const mutation = useDeleteSessionMutation(() => scope.value)
  /** 正在等二次确认的会话。 */
  const confirmingId = ref<string | null>(null)
  const error = ref<string | null>(null)

  function describe(e: unknown): string {
    if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : e.message
    return e instanceof Error ? e.message : '未知错误'
  }

  async function remove(id: string): Promise<void> {
    error.value = null
    confirmingId.value = null
    try {
      await mutation.mutateAsync(id)
    } catch (e) {
      error.value = `删除会话失败：${describe(e)}`
      return
    }
    if (sessionId.value !== id) return
    // 删掉的是当前会话：切到剩下的活动会话（其次第一个），都没有则清空。
    const rest = (sessions.value ?? []).filter((s) => s.id !== id)
    sessionId.value = (rest.find((s) => s.is_active) ?? rest[0])?.id ?? null
  }

  return { confirmingId, error, remove, deleting: computed(() => mutation.isPending.value) }
}
