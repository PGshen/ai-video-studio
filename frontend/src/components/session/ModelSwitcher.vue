<script setup lang="ts">
/**
 * 会话内换模型（计划 M5 T12，ADR 0012）：一个下拉，只有同 runtime、同 provider（Claude 还要同认证
 * 方式）且密钥已配置的可选，其余灰掉并在悬停提示里写原因（规则在 `modelChoice.ts`，与后端一致）。
 * 会话运行中禁用；换成功后下一轮开头时间线上会有一条「模型已从 A 换为 B」的提示。后端拒绝时
 * （例如排队中的 409）原样显示原因。
 */
import { computed } from 'vue'
import { errorMessage } from '@/api/http'
import type { SessionScope } from '@/composables/sessionScope'
import { useSwitchSessionModelMutation } from '@/composables/queries'
import type { ModelProfileOut, SessionOut } from '@/types/api'
import { switchBlockedReason, switchOptions } from './modelChoice'

const props = defineProps<{
  session: SessionOut
  profiles: ModelProfileOut[]
  scope: SessionScope
  /** 紧凑模式（放在输入框工具栏里）：不显示「当前模型」标签和说明文字，原因放进悬停提示。 */
  compact?: boolean
}>()

const mutation = useSwitchSessionModelMutation(() => props.scope)

const current = computed(() => props.profiles.find((p) => p.id === props.session.model_profile_id))
const options = computed(() => switchOptions(current.value, props.profiles))
const blocked = computed(() => switchBlockedReason(props.session.status))
const error = computed(() => (mutation.error.value ? errorMessage(mutation.error.value) : null))

function change(event: Event): void {
  const target = (event.target as HTMLSelectElement).value
  if (target === props.session.model_profile_id) return
  mutation.mutate({ sessionId: props.session.id, modelProfileId: target })
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1">
    <div class="flex items-center gap-2 text-sm">
      <label
        v-if="!compact"
        for="session-model"
        class="text-muted-foreground shrink-0"
      >当前模型</label>
      <select
        id="session-model"
        class="border-input bg-background min-w-0 rounded-md border px-2 text-sm disabled:opacity-60"
        :class="compact ? 'h-7 max-w-56 text-xs' : 'h-8 flex-1'"
        :value="session.model_profile_id"
        :disabled="blocked !== null || mutation.isPending.value"
        :title="blocked ?? '换成同一供应商的另一个模型，对话记忆保留'"
        data-testid="session-model"
        @change="change"
      >
        <option
          v-for="option in options"
          :key="option.profile.id"
          :value="option.profile.id"
          :disabled="option.disabledReason !== null"
          :title="option.disabledReason ?? ''"
        >
          {{ option.profile.name }}（{{ option.profile.model }}）{{
            option.disabledReason ? ` — ${option.disabledReason}` : ''
          }}
        </option>
      </select>
    </div>
    <p
      v-if="blocked && !compact"
      class="text-muted-foreground text-xs"
    >
      {{ blocked }}
    </p>
    <p
      v-if="error"
      class="text-destructive text-xs"
      data-testid="switch-error"
    >
      换模型失败：{{ error }}
    </p>
  </div>
</template>
