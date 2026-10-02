/**
 * 「没有会话时发送第一条消息」要用的建会话函数：用该阶段的默认模型（设置页里设的 → 第一个已配置的，
 * 与 `SessionList` 的 [新会话] 规则一致）新建会话，并把新会话选中。供 `SessionPanel` 的
 * `createSession` 属性使用。
 */
import { computed, type Ref } from 'vue'
import {
  useCreateSessionMutation,
  useModelProfilesQuery,
  useSettingsQuery,
} from '@/composables/queries'
import type { SessionScope } from '@/composables/sessionScope'
import { preselectProfileId } from './modelChoice'

export function useEnsureSession(
  scope: Ref<SessionScope>,
  sessionId: Ref<string | null>,
): () => Promise<string> {
  const { data: profiles } = useModelProfilesQuery()
  const { data: settings } = useSettingsQuery()
  const createSessionMutation = useCreateSessionMutation(() => scope.value)

  const stageKey = computed(() =>
    scope.value.kind === 'brainstorm' ? 'brainstorm' : scope.value.stage,
  )

  return async () => {
    const list = profiles.value
    const defaults = settings.value
    if (!list || !defaults) throw new Error('模型配置还在加载，请稍后再发')
    const profileId = preselectProfileId(list, defaults.stage_default_profile, stageKey.value)
    if (!list.find((p) => p.id === profileId)?.key_configured) {
      throw new Error('没有已配置密钥的模型，请先到设置页配置')
    }
    const session = await createSessionMutation.mutateAsync({ model_profile_id: profileId })
    sessionId.value = session.id
    return session.id
  }
}
