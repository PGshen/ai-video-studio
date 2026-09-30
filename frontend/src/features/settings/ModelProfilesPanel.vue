<script setup lang="ts">
/**
 * 「模型配置」子页（计划 M5 T10）：列表、新增、编辑、删除。内置配置可以编辑但不能删除；
 * 被会话或阶段默认模型引用的配置删除时后端返回 409 和原因，原样显示。
 * 环境变量决定的字段在编辑对话框里只读并说明。
 */
import { computed, ref } from 'vue'
import { errorMessage } from '@/api/http'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useCreateModelProfileMutation,
  useDeleteModelProfileMutation,
  useModelProfilesQuery,
  useUpdateModelProfileMutation,
} from '@/composables/queries'
import type { ModelProfileCreate, ModelProfileOut, ModelProfilePatch } from '@/types/api'
import ModelProfileDialog from './ModelProfileDialog.vue'
import { keyStatus } from './settingsView'

const { data: profiles, isPending, error: loadError } = useModelProfilesQuery()
const createMutation = useCreateModelProfileMutation()
const updateMutation = useUpdateModelProfileMutation()
const deleteMutation = useDeleteModelProfileMutation()

const dialogOpen = ref(false)
const editing = ref<ModelProfileOut | null>(null)
const deleting = ref<ModelProfileOut | null>(null)
const deleteDialogOpen = ref(false)
const deleteError = ref<string | null>(null)

const saving = computed(() => createMutation.isPending.value || updateMutation.isPending.value)
const saveError = computed(() => {
  const error = createMutation.error.value ?? updateMutation.error.value
  return error ? errorMessage(error) : null
})

function openCreate(): void {
  editing.value = null
  createMutation.reset()
  updateMutation.reset()
  dialogOpen.value = true
}

function openEdit(profile: ModelProfileOut): void {
  editing.value = profile
  createMutation.reset()
  updateMutation.reset()
  dialogOpen.value = true
}

async function create(body: ModelProfileCreate): Promise<void> {
  try {
    await createMutation.mutateAsync(body)
    dialogOpen.value = false
  } catch {
    // 错误显示在对话框里（saveError）。
  }
}

async function update(payload: { id: string; patch: ModelProfilePatch }): Promise<void> {
  try {
    await updateMutation.mutateAsync(payload)
    dialogOpen.value = false
  } catch {
    // 同上。
  }
}

function askDelete(profile: ModelProfileOut): void {
  deleting.value = profile
  deleteError.value = null
  deleteDialogOpen.value = true
}

async function confirmDelete(event: Event): Promise<void> {
  // 阻止对话框自动关闭：失败（409）时要留在对话框里显示原因。
  event.preventDefault()
  if (!deleting.value) return
  try {
    await deleteMutation.mutateAsync(deleting.value.id)
    deleteDialogOpen.value = false
  } catch (error) {
    deleteError.value = errorMessage(error)
  }
}

function price(value: number | null): string {
  return value === null ? '—' : `$${value}`
}

function budget(profile: ModelProfileOut): string {
  const cost = profile.max_cost_per_turn === null ? '不限' : `$${profile.max_cost_per_turn}`
  const steps = profile.max_steps_per_turn === null ? '不限' : `${profile.max_steps_per_turn} 步`
  return `${cost} / ${steps}`
}
</script>

<template>
  <section class="flex flex-col gap-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-lg font-medium">
          模型配置
        </h2>
        <p class="text-muted-foreground text-sm">
          决定会话用哪个模型、走哪种运行时，以及单价和每轮预算。API key 的值仍然只放在 backend/.env。
        </p>
      </div>
      <Button
        data-testid="add-profile"
        @click="openCreate"
      >
        新增配置
      </Button>
    </div>

    <p
      v-if="isPending"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
    <p
      v-else-if="loadError"
      class="text-destructive text-sm"
    >
      加载失败：{{ errorMessage(loadError) }}
    </p>

    <div
      v-else
      class="overflow-x-auto rounded-md border"
    >
      <table class="w-full text-sm">
        <thead class="bg-muted/50 text-muted-foreground text-left">
          <tr>
            <th class="px-3 py-2 font-medium">
              名称
            </th>
            <th class="px-3 py-2 font-medium">
              供应商 / 模型
            </th>
            <th class="px-3 py-2 font-medium">
              运行时
            </th>
            <th class="px-3 py-2 font-medium">
              密钥
            </th>
            <th class="px-3 py-2 font-medium">
              单价（入 / 出，每百万 token）
            </th>
            <th class="px-3 py-2 font-medium">
              每轮预算（成本 / 步数）
            </th>
            <th class="px-3 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="profile in profiles"
            :key="profile.id"
            class="border-t align-top"
            :data-testid="`profile-row-${profile.name}`"
          >
            <td class="px-3 py-2">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="font-medium">{{ profile.name }}</span>
                <Badge
                  v-if="profile.builtin"
                  variant="secondary"
                >
                  内置
                </Badge>
              </div>
            </td>
            <td class="px-3 py-2">
              <div>{{ profile.provider }}</div>
              <div class="text-muted-foreground text-xs">
                {{ profile.model }}
              </div>
              <div
                v-if="profile.base_url"
                class="text-muted-foreground text-xs"
              >
                {{ profile.base_url }}
              </div>
              <div
                v-if="profile.env_override.length"
                class="text-xs text-amber-600"
              >
                环境变量决定：{{ profile.env_override.join('、') }}
              </div>
            </td>
            <td class="px-3 py-2">
              {{ profile.runtime }}
            </td>
            <td class="px-3 py-2">
              <Badge :variant="keyStatus(profile) === '未配置' ? 'destructive' : 'outline'">
                {{ keyStatus(profile) }}
              </Badge>
              <div
                v-if="profile.api_key_env"
                class="text-muted-foreground mt-1 font-mono text-xs"
              >
                {{ profile.api_key_env }}
              </div>
            </td>
            <td class="px-3 py-2">
              {{ price(profile.price_input) }} / {{ price(profile.price_output) }}
            </td>
            <td class="px-3 py-2">
              {{ budget(profile) }}
            </td>
            <td class="px-3 py-2 text-right whitespace-nowrap">
              <Button
                variant="outline"
                size="sm"
                :data-testid="`edit-${profile.name}`"
                @click="openEdit(profile)"
              >
                编辑
              </Button>
              <Button
                variant="ghost"
                size="sm"
                :disabled="profile.builtin"
                :title="profile.builtin ? '内置配置不能删除，可以编辑' : ''"
                :data-testid="`delete-${profile.name}`"
                @click="askDelete(profile)"
              >
                删除
              </Button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ModelProfileDialog
      v-model:open="dialogOpen"
      :profile="editing"
      :pending="saving"
      :error="saveError"
      @create="create"
      @update="update"
    />

    <AlertDialog v-model:open="deleteDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除模型配置 {{ deleting?.name }}？</AlertDialogTitle>
          <AlertDialogDescription>
            删除后不能恢复。被会话或阶段默认模型使用的配置删不掉，会告诉你是谁在用。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <p
          v-if="deleteError"
          class="text-destructive text-sm"
        >
          {{ deleteError }}
        </p>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            :disabled="deleteMutation.isPending.value"
            @click="confirmDelete"
          >
            确认删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>
