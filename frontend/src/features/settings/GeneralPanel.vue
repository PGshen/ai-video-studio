<script setup lang="ts">
/**
 * 「通用」子页（计划 M5 T10）：各阶段的默认模型（新建会话时预选）和联网模式。
 * 联网模式的界面设置覆盖环境变量 `STUDIO_WEB_MODE`，下一轮起生效（TurnRunner 每轮重新读）；
 * 选原生联网时说明没有 URL 来源保护，并标注 OpenAI 托管搜索经 OpenRouter 未验证（TD-39）。
 */
import { computed } from 'vue'
import { errorMessage } from '@/api/http'
import { Button } from '@/components/ui/button'
import {
  useModelProfilesQuery,
  usePatchSettingsMutation,
  useSettingsQuery,
} from '@/composables/queries'
import type { WebMode } from '@/types/api'
import {
  DEFAULT_PROFILE_STAGES,
  WEB_MODE_HINTS,
  WEB_MODE_LABELS,
  defaultProfileChoices,
  webModeNotes,
  webModeSourceText,
} from './settingsView'

const { data: settings, isPending, error: loadError } = useSettingsQuery()
const { data: profiles } = useModelProfilesQuery()
const patch = usePatchSettingsMutation()

const patchError = computed(() => (patch.error.value ? errorMessage(patch.error.value) : null))
const webModes = Object.keys(WEB_MODE_LABELS) as WebMode[]

function currentDefault(stage: string): string {
  return settings.value?.stage_default_profile[stage] ?? ''
}

function setStageDefault(stage: string, event: Event): void {
  const select = event.target as HTMLSelectElement
  const value = select.value
  patch.mutate(
    { stage_default_profile: { [stage]: value === '' ? null : value } },
    {
      // 被拒绝时缓存里的设置没变，Vue 不会重渲染；把下拉手动改回去，免得看起来像已生效。
      onError: () => {
        select.value = currentDefault(stage)
      },
    },
  )
}

function setWebMode(mode: WebMode | null): void {
  patch.mutate({ web_mode: mode })
}
</script>

<template>
  <section class="flex max-w-3xl flex-col gap-8">
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

    <template v-else-if="settings">
      <div class="flex flex-col gap-3">
        <div>
          <h2 class="text-lg font-medium">
            各阶段默认模型
          </h2>
          <p class="text-muted-foreground text-sm">
            新建会话时预选这个模型；不预设就选第一个已配置的。只列出密钥已配置的模型。
          </p>
        </div>
        <div
          v-for="stage in DEFAULT_PROFILE_STAGES"
          :key="stage.key"
          class="flex items-center gap-3"
        >
          <label
            :for="`default-${stage.key}`"
            class="w-20 text-sm"
          >
            {{ stage.label }}
          </label>
          <select
            :id="`default-${stage.key}`"
            class="border-input bg-background h-9 w-64 rounded-md border px-2 text-sm"
            :value="currentDefault(stage.key)"
            :data-testid="`default-${stage.key}`"
            @change="setStageDefault(stage.key, $event)"
          >
            <option value="">
              不预设
            </option>
            <option
              v-for="profile in defaultProfileChoices(profiles ?? [], currentDefault(stage.key) || null)"
              :key="profile.id"
              :value="profile.id"
            >
              {{ profile.name }}（{{ profile.model }}）{{ profile.key_configured ? '' : ' · 密钥未配置' }}
            </option>
          </select>
        </div>
      </div>

      <div class="flex flex-col gap-3">
        <div>
          <h2 class="text-lg font-medium">
            联网模式
          </h2>
          <p class="text-muted-foreground text-sm">
            头脑风暴和选题阶段怎么联网。叙事和动画在任何模式下都不联网。改动下一轮对话起生效。
          </p>
        </div>

        <div
          class="flex flex-col gap-2"
          role="radiogroup"
          aria-label="联网模式"
        >
          <label
            v-for="mode in webModes"
            :key="mode"
            class="flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm"
            :class="{ 'border-primary': settings.web_mode === mode }"
          >
            <input
              type="radio"
              name="web-mode"
              class="mt-1"
              :value="mode"
              :checked="settings.web_mode === mode"
              :data-testid="`web-mode-${mode}`"
              @change="setWebMode(mode)"
            >
            <span>
              <span class="font-medium">{{ WEB_MODE_LABELS[mode] }}</span>
              <span class="text-muted-foreground block">{{ WEB_MODE_HINTS[mode] }}</span>
            </span>
          </label>
        </div>

        <p
          class="text-muted-foreground text-sm"
          data-testid="web-mode-source"
        >
          {{ webModeSourceText(settings) }}
        </p>
        <div v-if="settings.web_mode_source === 'ui'">
          <Button
            variant="outline"
            size="sm"
            data-testid="clear-web-mode"
            :disabled="patch.isPending.value"
            @click="setWebMode(null)"
          >
            清除界面设置，回到环境变量
          </Button>
        </div>

        <ul
          v-if="webModeNotes(settings.web_mode).length"
          class="flex flex-col gap-1 rounded-md border border-amber-500/50 bg-amber-500/5 p-3 text-sm"
          data-testid="web-mode-notes"
        >
          <li
            v-for="note in webModeNotes(settings.web_mode)"
            :key="note"
          >
            {{ note }}
          </li>
        </ul>
      </div>

      <p
        v-if="patchError"
        class="text-destructive text-sm"
      >
        保存失败：{{ patchError }}
      </p>
    </template>
  </section>
</template>
