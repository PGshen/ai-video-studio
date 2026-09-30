<script setup lang="ts">
/**
 * 模型配置下拉 + [新会话] + 当前阶段的会话列表（任务简报 T13，控制者裁定
 * 4）。选中的会话 id 通过 `v-model:session-id` 双向绑定给
 * `SessionPanel`/`useSessionStream` 用。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  useCreateSessionMutation,
  useModelProfilesQuery,
  useSessionsQuery,
  useSettingsQuery,
} from '@/composables/queries'
import { ApiError } from '@/api/http'
import type { SessionScope } from '@/composables/sessionScope'
import ModelSwitcher from './ModelSwitcher.vue'
import { preselectProfileId } from './modelChoice'

const props = defineProps<{
  scope: SessionScope
}>()

const sessionId = defineModel<string | null>('sessionId', { default: null })

const { data: profiles } = useModelProfilesQuery()
const { data: settings } = useSettingsQuery()
const { data: sessions } = useSessionsQuery(() => props.scope)
const createSessionMutation = useCreateSessionMutation(() => props.scope)

/** 默认模型按阶段取：头脑风暴是 `brainstorm`，项目阶段是它自己的阶段名。 */
const stageKey = computed(() => (props.scope.kind === 'brainstorm' ? 'brainstorm' : props.scope.stage))

// 预选（M5 T12）：该阶段的默认模型（设置页里设的）→ 第一个已配置的。使用者手动选过之后不再
// 覆盖；切换阶段时重新预选。
const selectedProfileId = ref<string>('')
let userPicked = false
watch(stageKey, () => {
  userPicked = false
})
watch(
  [profiles, settings, stageKey],
  () => {
    if (!profiles.value || !settings.value || userPicked) return
    selectedProfileId.value = preselectProfileId(
      profiles.value,
      settings.value.stage_default_profile,
      stageKey.value,
    )
  },
  { immediate: true },
)
function onProfilePicked(value: unknown): void {
  userPicked = true
  selectedProfileId.value = String(value)
}

const currentSession = computed(() => sessions.value?.find((s) => s.id === sessionId.value))

// 默认选中当前阶段已有会话里标记为 active 的那个，其次是列表第一个；只在
// 还没有选中任何会话、且列表刚加载出来时做一次，不覆盖用户后续手动切换。
watch(
  sessions,
  (list) => {
    if (!list || sessionId.value) return
    const active = list.find((s) => s.is_active) ?? list[0]
    if (active) sessionId.value = active.id
  },
  { immediate: true },
)

async function createSession(): Promise<void> {
  if (!selectedProfileId.value) return
  const session = await createSessionMutation.mutateAsync({
    model_profile_id: selectedProfileId.value,
  })
  sessionId.value = session.id
}

const createError = computed(() => {
  const error = createSessionMutation.error.value
  if (!error) return null
  if (error instanceof ApiError) return typeof error.detail === 'string' ? error.detail : error.message
  return error instanceof Error ? error.message : '未知错误'
})
</script>

<template>
  <div class="flex flex-col gap-2 border-b pb-3">
    <div class="flex items-center gap-2">
      <Select
        :model-value="selectedProfileId"
        @update:model-value="onProfilePicked"
      >
        <SelectTrigger class="w-48">
          <SelectValue placeholder="选择模型配置" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem
            v-for="profile in profiles"
            :key="profile.id"
            :value="profile.id"
            :disabled="!profile.key_configured"
          >
            {{ profile.name }}{{ profile.key_configured ? '' : '（未配置密钥）' }}
          </SelectItem>
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        :disabled="!selectedProfileId || createSessionMutation.isPending.value"
        @click="createSession"
      >
        新会话
      </Button>
    </div>
    <p
      v-if="createError"
      class="text-destructive text-sm"
    >
      创建会话失败：{{ createError }}
    </p>

    <div
      v-if="sessions && sessions.length > 0"
      class="flex flex-wrap gap-1"
    >
      <button
        v-for="session in sessions"
        :key="session.id"
        type="button"
        class="rounded border px-2 py-1 text-xs"
        :class="
          session.id === sessionId
            ? 'border-primary bg-primary/10 text-primary'
            : 'text-muted-foreground'
        "
        @click="sessionId = session.id"
      >
        {{ session.title ?? session.id.slice(0, 8) }}
      </button>
    </div>

    <ModelSwitcher
      v-if="currentSession && profiles"
      :key="currentSession.id"
      :session="currentSession"
      :profiles="profiles"
      :scope="scope"
    />
  </div>
</template>
