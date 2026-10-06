<script setup lang="ts">
/**
 * 工作台左侧竖栏里的会话区：[新会话] + 会话列表。选中的会话 id 通过 `v-model:session-id`
 * 交给 `SessionPanel`。模型不在这里选：[新会话] 用该阶段的默认模型（设置页里设的），旁边的下拉
 * 可以换一个模型新建；会话内换模型在输入框工具栏（`ModelSwitcher`）。
 * `collapsed`（竖栏折叠）时只剩两个图标：会话气泡菜单（列表 + 新建）和快捷新建。
 * 头脑风暴抽屉和风格编辑用 `SessionSwitcher`（一行气泡菜单，可删除会话）。
 */
import { Check, ChevronDown, MessagesSquare, Plus, Trash2 } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/http'
import RailGroup from '@/components/RailGroup.vue'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useCreateSessionMutation,
  useModelProfilesQuery,
  useSessionsQuery,
  useSettingsQuery,
} from '@/composables/queries'
import type { SessionScope } from '@/composables/sessionScope'
import { preselectProfileId } from './modelChoice'
import { useSessionDelete } from './useSessionDelete'

const props = defineProps<{
  scope: SessionScope
  collapsed?: boolean
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

const stageKey = computed(() => (props.scope.kind === 'brainstorm' ? 'brainstorm' : props.scope.stage))

// 默认模型：该阶段的默认模型 → 第一个已配置的（与 SessionSwitcher 的预选规则一致）。
const defaultProfileId = computed(() =>
  profiles.value && settings.value
    ? preselectProfileId(profiles.value, settings.value.stage_default_profile, stageKey.value)
    : '',
)

// 默认选中已有会话里标记为 active 的那个，其次是列表第一个；只在还没有选中且列表刚加载出来时做一次。
watch(
  sessions,
  (list) => {
    if (!list || sessionId.value) return
    const active = list.find((s) => s.is_active) ?? list[0]
    if (active) sessionId.value = active.id
  },
  { immediate: true },
)

async function createSession(profileId: string): Promise<void> {
  if (!profileId) return
  const session = await createSessionMutation.mutateAsync({ model_profile_id: profileId })
  sessionId.value = session.id
}

const createError = computed(() => {
  const error = createSessionMutation.error.value
  if (!error) return null
  if (error instanceof ApiError) return typeof error.detail === 'string' ? error.detail : error.message
  return error instanceof Error ? error.message : '未知错误'
})

/** 折叠态气泡菜单开关时清掉行内确认。 */
const menuOpen = ref(false)
watch(menuOpen, () => {
  confirmingId.value = null
})

const creating = computed(() => createSessionMutation.isPending.value)

function profileLabel(profile: { id: string; name: string; key_configured: boolean }): string {
  return `${profile.name}${profile.key_configured ? '' : '（未配置密钥）'}${profile.id === defaultProfileId.value ? '（默认）' : ''}`
}
</script>

<template>
  <RailGroup
    title="会话"
    :collapsed="collapsed"
  >
    <!-- 折叠态：会话图标点开是气泡（会话列表 + 新建），再加一个快捷新建。 -->
    <div
      v-if="collapsed"
      class="flex flex-col items-center gap-1"
      data-testid="session-list-collapsed"
    >
      <DropdownMenu v-model:open="menuOpen">
        <DropdownMenuTrigger as-child>
          <Button
            variant="ghost"
            size="icon-sm"
            title="会话"
          >
            <MessagesSquare />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side="right"
          align="start"
          class="w-56"
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
                <span class="min-w-0 flex-1 truncate">删除「{{ session.title ?? '新会话' }}」？</span>
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
                @select="sessionId = session.id"
              >
                <Check
                  class="shrink-0"
                  :class="session.id === sessionId ? 'opacity-100' : 'opacity-0'"
                />
                <span class="min-w-0 flex-1 truncate">{{ session.title ?? '新会话' }}</span>
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
          <DropdownMenuSeparator />
          <DropdownMenuItem
            :disabled="!defaultProfileId || creating"
            @select="createSession(defaultProfileId)"
          >
            <Plus /> 新会话
          </DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger :disabled="creating">
              用其它模型新建
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem
                v-for="profile in profiles"
                :key="profile.id"
                :disabled="!profile.key_configured"
                @select="createSession(profile.id)"
              >
                {{ profileLabel(profile) }}
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button
        variant="ghost"
        size="icon-sm"
        title="新会话"
        :disabled="!defaultProfileId || creating"
        @click="createSession(defaultProfileId)"
      >
        <Plus />
      </Button>
      <MessagesSquare
        v-if="createError || deleteError"
        class="text-destructive size-4"
        :title="createError ? `创建会话失败：${createError}` : deleteError ?? ''"
      />
    </div>

    <div
      v-else
      class="flex min-h-0 flex-1 flex-col gap-2"
      data-testid="session-list"
    >
      <ButtonGroup class="w-full">
        <Button
          variant="outline"
          size="sm"
          class="flex-1"
          :disabled="!defaultProfileId || creating"
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
          <DropdownMenuContent align="start">
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

      <p
        v-if="createError"
        class="text-destructive text-xs"
      >
        创建会话失败：{{ createError }}
      </p>
      <p
        v-if="deleteError"
        class="text-destructive text-xs"
      >
        {{ deleteError }}
      </p>

      <ul class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
        <li
          v-for="session in sessions"
          :key="session.id"
        >
          <div
            v-if="confirmingId === session.id"
            class="flex items-center gap-1 rounded-md px-2 py-1 text-sm"
            data-testid="session-delete-confirm"
          >
            <span
              class="min-w-0 flex-1 truncate"
              :title="session.title ?? '新会话'"
            >确认删除？</span>
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
          <div
            v-else
            class="flex items-center rounded-md"
            :class="
              session.id === sessionId
                ? 'bg-primary/10 text-primary font-medium'
                : 'text-muted-foreground hover:bg-muted'
            "
          >
            <button
              type="button"
              class="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm"
              :title="session.title ?? session.id"
              @click="sessionId = session.id"
            >
              {{ session.title ?? '新会话' }}
            </button>
            <button
              type="button"
              class="text-muted-foreground hover:text-destructive mr-1 shrink-0 rounded p-1"
              title="删除会话"
              data-testid="session-delete"
              @click="confirmingId = session.id"
            >
              <Trash2 class="size-4" />
            </button>
          </div>
        </li>
        <li
          v-if="sessions && sessions.length === 0"
          class="text-muted-foreground px-2 text-xs"
        >
          还没有会话
        </li>
      </ul>
    </div>
  </RailGroup>
</template>
