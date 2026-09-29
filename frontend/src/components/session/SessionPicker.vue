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
import { useCreateSessionMutation, useModelProfilesQuery, useSessionsQuery } from '@/composables/queries'
import { ApiError } from '@/api/http'
import type { SessionScope } from '@/composables/sessionScope'

const props = defineProps<{
  scope: SessionScope
}>()

const sessionId = defineModel<string | null>('sessionId', { default: null })

const { data: profiles } = useModelProfilesQuery()
const { data: sessions } = useSessionsQuery(() => props.scope)
const createSessionMutation = useCreateSessionMutation(() => props.scope)

const selectedProfileId = ref<string>('')
watch(
  profiles,
  (list) => {
    if (!list || selectedProfileId.value) return
    const configured = list.find((p) => p.key_configured)
    selectedProfileId.value = (configured ?? list[0])?.id ?? ''
  },
  { immediate: true },
)

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
      <Select v-model="selectedProfileId">
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
  </div>
</template>
