<script setup lang="ts">
/**
 * 新建/编辑模型配置的对话框（计划 M5 T10）。`profile` 为 `null` 是新建；编辑时名称、供应商、
 * 运行时不可改；环境变量决定的字段（`env_override`）禁用并说明。校验和表单 ↔ 请求体的转换在
 * `profileForm.ts`（与后端规则一致），这里只管展示；提交由面板调接口。
 * API key 的**值**不在这里录入：只填环境变量的名字，key 写在 backend/.env。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ModelProfileCreate, ModelProfileOut, ModelProfilePatch } from '@/types/api'
import {
  USER_RUNTIMES,
  emptyProfileForm,
  formFromProfile,
  toCreateBody,
  toPatchBody,
  validateProfileForm,
  zeroBudgetWarning,
  type ProfileFormErrors,
  type ProfileFormValues,
} from './profileForm'
import { isFieldLocked } from './settingsView'

const props = defineProps<{
  profile: ModelProfileOut | null
  pending?: boolean
  error?: string | null
}>()
const emit = defineEmits<{
  (e: 'create', body: ModelProfileCreate): void
  (e: 'update', payload: { id: string; patch: ModelProfilePatch }): void
}>()

const open = defineModel<boolean>('open', { default: false })
const values = ref<ProfileFormValues>(emptyProfileForm())
const errors = ref<ProfileFormErrors>({})
const nothingChanged = ref(false)

const mode = computed<'create' | 'edit'>(() => (props.profile ? 'edit' : 'create'))
const warning = computed(() => zeroBudgetWarning(values.value))

watch(open, (isOpen) => {
  if (!isOpen) return
  values.value = props.profile ? formFromProfile(props.profile) : emptyProfileForm()
  errors.value = {}
  nothingChanged.value = false
})

function locked(field: string): boolean {
  return props.profile !== null && isFieldLocked(props.profile, field)
}

function submit(): void {
  errors.value = validateProfileForm(values.value, mode.value)
  nothingChanged.value = false
  if (Object.keys(errors.value).length > 0) return
  if (props.profile) {
    const patch = toPatchBody(values.value, props.profile)
    if (Object.keys(patch).length === 0) {
      nothingChanged.value = true
      return
    }
    emit('update', { id: props.profile.id, patch })
  } else {
    emit('create', toCreateBody(values.value))
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="max-h-[90vh] overflow-y-auto sm:max-w-xl">
      <DialogHeader>
        <DialogTitle>{{ profile ? `编辑模型配置：${profile.name}` : '新增模型配置' }}</DialogTitle>
        <DialogDescription>
          API key 的值不在这里填：只写环境变量的名字，key 本身放在 backend/.env 里。
        </DialogDescription>
      </DialogHeader>

      <div class="grid grid-cols-2 gap-3">
        <div class="flex flex-col gap-1.5">
          <Label for="profile-name">名称</Label>
          <Input
            id="profile-name"
            v-model="values.name"
            :disabled="mode === 'edit'"
            placeholder="例如 my-gpt"
          />
          <p
            v-if="errors.name"
            class="text-destructive text-xs"
          >
            {{ errors.name }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-runtime">运行时</Label>
          <select
            id="profile-runtime"
            v-model="values.runtime"
            class="border-input bg-background h-9 rounded-md border px-2 text-sm disabled:opacity-50"
            :disabled="mode === 'edit'"
          >
            <option
              v-for="runtime in USER_RUNTIMES"
              :key="runtime"
              :value="runtime"
            >
              {{ runtime }}
            </option>
            <option
              v-if="mode === 'edit' && !(USER_RUNTIMES as readonly string[]).includes(values.runtime)"
              :value="values.runtime"
            >
              {{ values.runtime }}
            </option>
          </select>
          <p
            v-if="errors.runtime"
            class="text-destructive text-xs"
          >
            {{ errors.runtime }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-provider">供应商（provider）</Label>
          <Input
            id="profile-provider"
            v-model="values.provider"
            :disabled="mode === 'edit'"
            placeholder="openai / anthropic / litellm …"
          />
          <p
            v-if="errors.provider"
            class="text-destructive text-xs"
          >
            {{ errors.provider }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-model">模型名</Label>
          <Input
            id="profile-model"
            v-model="values.model"
            :disabled="locked('model')"
          />
          <p
            v-if="locked('model')"
            class="text-muted-foreground text-xs"
          >
            由环境变量决定，改 backend/.env
          </p>
          <p
            v-if="errors.model"
            class="text-destructive text-xs"
          >
            {{ errors.model }}
          </p>
        </div>
        <div class="col-span-2 flex flex-col gap-1.5">
          <Label for="profile-base-url">接入地址（base_url，可留空）</Label>
          <Input
            id="profile-base-url"
            v-model="values.base_url"
            :disabled="locked('base_url')"
            placeholder="https://openrouter.ai/api/v1"
          />
          <p
            v-if="locked('base_url')"
            class="text-muted-foreground text-xs"
          >
            由环境变量决定，改 backend/.env
          </p>
          <p
            v-if="errors.base_url"
            class="text-destructive text-xs"
          >
            {{ errors.base_url }}
          </p>
        </div>
        <div class="col-span-2 flex flex-col gap-1.5">
          <Label for="profile-key-env">API key 的环境变量名</Label>
          <Input
            id="profile-key-env"
            v-model="values.api_key_env"
            placeholder="例如 OPENAI_API_KEY；claude 可以留空（使用本机登录）"
          />
          <p
            v-if="errors.api_key_env"
            class="text-destructive text-xs"
          >
            {{ errors.api_key_env }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-price-in">输入单价（美元 / 百万 token）</Label>
          <Input
            id="profile-price-in"
            v-model="values.price_input"
            :disabled="locked('price_input')"
            inputmode="decimal"
          />
          <p
            v-if="locked('price_input')"
            class="text-muted-foreground text-xs"
          >
            由环境变量决定，改 backend/.env
          </p>
          <p
            v-if="errors.price_input"
            class="text-destructive text-xs"
          >
            {{ errors.price_input }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-price-out">输出单价（美元 / 百万 token）</Label>
          <Input
            id="profile-price-out"
            v-model="values.price_output"
            :disabled="locked('price_output')"
            inputmode="decimal"
          />
          <p
            v-if="locked('price_output')"
            class="text-muted-foreground text-xs"
          >
            由环境变量决定，改 backend/.env
          </p>
          <p
            v-if="errors.price_output"
            class="text-destructive text-xs"
          >
            {{ errors.price_output }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-max-cost">单轮成本上限（美元，留空不限）</Label>
          <Input
            id="profile-max-cost"
            v-model="values.max_cost_per_turn"
            inputmode="decimal"
          />
          <p
            v-if="errors.max_cost_per_turn"
            class="text-destructive text-xs"
          >
            {{ errors.max_cost_per_turn }}
          </p>
          <p
            v-else-if="warning"
            class="text-xs text-amber-600"
          >
            {{ warning }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="profile-max-steps">单轮步数上限（留空不限）</Label>
          <Input
            id="profile-max-steps"
            v-model="values.max_steps_per_turn"
            inputmode="numeric"
          />
          <p
            v-if="errors.max_steps_per_turn"
            class="text-destructive text-xs"
          >
            {{ errors.max_steps_per_turn }}
          </p>
        </div>
        <label class="col-span-2 flex items-center gap-2 text-sm">
          <input
            v-model="values.supports_vision"
            type="checkbox"
          >
          支持图片输入（动画阶段的关键帧预览需要）
        </label>
      </div>

      <p
        v-if="error"
        class="text-destructive text-sm"
      >
        {{ error }}
      </p>
      <p
        v-if="nothingChanged"
        class="text-muted-foreground text-sm"
      >
        没有改动。
      </p>

      <DialogFooter>
        <Button
          variant="outline"
          @click="open = false"
        >
          取消
        </Button>
        <Button
          :disabled="pending"
          @click="submit"
        >
          {{ pending ? '保存中…' : '保存' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
