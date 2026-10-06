<script setup lang="ts">
/**
 * 对话区顶部的会话条（头脑风暴、风格对话用）：一个显示当前会话标题的按钮，点开是气泡菜单，
 * 里面列出全部会话，可以切换、删除（行内二次确认），新建放在右侧按钮组（点「新会话」用默认模型，旁边的下拉箭头选其它模型）。
 * 会话再多也只占一行。模型不在这里选：新会话用该范围的默认模型，会话内换模型在输入框工具栏
 * （`SessionModelTool`）。选中的会话 id 通过 `v-model:session-id` 交给 `SessionPanel`。
 */
import { Check, ChevronDown, Plus, Trash2 } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/http'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useCreateSessionMutation,
  useModelProfilesQuery,
  useSessionsQuery,
  useSettingsQuery,
} from '@/composables/queries'
import { scopeStageKey, type SessionScope } from '@/composables/sessionScope'
import { preselectProfileId } from './modelChoice'
import { useSessionDelete } from './useSessionDelete'

const props = defineProps<{
  scope: SessionScope
}>()

const sessionId = defineModel<string | null>('sessionId', { default: null })

const { data: profiles } = useModelProfilesQuery()
const { data: settings } = useSettingsQuery()
const { data: sessions } = useSessionsQuery(() => props.scope)
const createSessionMutation = useCreateSessionMutation(() => props.scope)
const {
  confirmingId,
  error: deleteError,
  remove: deleteSession,
} = useSessionDelete(
  computed(() => props.scope),
  sessionId,
)

const defaultProfileId = computed(() =>
  profiles.value && settings.value
    ? preselectProfileId(
        profiles.value,
        settings.value.stage_default_profile,
        scopeStageKey(props.scope),
      )
    : '',
)

// 默认选中已有会话里标记为 active 的那个，其次是列表第一个；只在还没有选中且列表加载出来时做一次。
watch(
  sessions,
  (list) => {
    if (!list || sessionId.value) return
    const active = list.find((s) => s.is_active) ?? list[0]
    if (active) sessionId.value = active.id
  },
  { immediate: true },
)

const currentSession = computed(() => sessions.value?.find((s) => s.id === sessionId.value))
const currentLabel = computed(() =>
  currentSession.value ? titleOf(currentSession.value) : '还没有会话',
)

function titleOf(session: { id: string; title: string | null }): string {
  return session.title ?? '新会话'
}

const open = ref(false)
watch(open, () => {
  confirmingId.value = null
})

const error = ref<string | null>(null)
function describeError(e: unknown): string {
  if (e instanceof ApiError) return typeof e.detail === 'string' ? e.detail : e.message
  return e instanceof Error ? e.message : '未知错误'
}

async function createSession(profileId: string): Promise<void> {
  if (!profileId) return
  error.value = null
  try {
    const session = await createSessionMutation.mutateAsync({ model_profile_id: profileId })
    sessionId.value = session.id
  } catch (e) {
    error.value = `创建会话失败：${describeError(e)}`
  }
}

function profileLabel(profile: { id: string; name: string; key_configured: boolean }): string {
  return `${profile.name}${profile.key_configured ? '' : '（未配置密钥）'}${profile.id === defaultProfileId.value ? '（默认）' : ''}`
}

const creating = computed(() => createSessionMutation.isPending.value)
</script>

<template>
  <div
    class="flex flex-col gap-1"
    data-testid="session-switcher"
  >
    <div class="flex items-center gap-2">
      <DropdownMenu v-model:open="open">
        <DropdownMenuTrigger as-child>
          <Button
            variant="outline"
            size="sm"
            class="min-w-0 flex-1 justify-between"
            data-testid="session-switcher-trigger"
            :title="currentLabel"
          >
            <span class="min-w-0 truncate">{{ currentLabel }}</span>
            <ChevronDown />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          class="w-72"
        >
          <DropdownMenuLabel>会话</DropdownMenuLabel>
          <div class="max-h-64 overflow-y-auto">
            <template
              v-for="session in sessions"
              :key="session.id"
            >
              <div
                v-if="confirmingId === session.id"
                class="flex items-center gap-2 px-2 py-1.5 text-sm"
                data-testid="session-delete-confirm"
              >
                <span class="min-w-0 flex-1 truncate">删除「{{ titleOf(session) }}」？</span>
                <Button
                  size="xs"
                  variant="destructive"
                  data-testid="session-delete-yes"
                  @click="deleteSession(session.id)"
                >
                  删除
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  @click="confirmingId = null"
                >
                  取消
                </Button>
              </div>
              <DropdownMenuItem
                v-else
                class="group"
                data-testid="session-item"
                @select="sessionId = session.id"
              >
                <Check
                  class="shrink-0"
                  :class="session.id === sessionId ? 'opacity-100' : 'opacity-0'"
                />
                <span
                  class="min-w-0 flex-1 truncate"
                  :title="titleOf(session)"
                >{{ titleOf(session) }}</span>
                <button
                  type="button"
                  class="text-muted-foreground hover:text-destructive hover:bg-destructive/10 -my-1 -mr-1 shrink-0 rounded p-1.5"
                  title="删除会话"
                  data-testid="session-delete"
                  @click.stop.prevent="confirmingId = session.id"
                  @pointerdown.stop
                  @pointerup.stop
                >
                  <Trash2 class="size-4" />
                </button>
              </DropdownMenuItem>
            </template>
          </div>
          <DropdownMenuItem
            v-if="sessions && sessions.length === 0"
            disabled
          >
            还没有会话
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ButtonGroup>
        <Button
          variant="outline"
          size="sm"
          :disabled="!defaultProfileId || creating"
          data-testid="session-new"
          @click="createSession(defaultProfileId)"
        >
          <Plus /> 新会话
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button
              variant="outline"
              size="icon-sm"
              title="选择模型新建会话"
              :disabled="creating"
            >
              <ChevronDown />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>用此模型新建会话</DropdownMenuLabel>
            <DropdownMenuItem
              v-for="profile in profiles"
              :key="profile.id"
              :disabled="!profile.key_configured"
              @select="createSession(profile.id)"
            >
              {{ profileLabel(profile) }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </ButtonGroup>
    </div>
    <p
      v-if="error || deleteError"
      class="text-destructive text-xs"
    >
      {{ error ?? deleteError }}
    </p>
  </div>
</template>
