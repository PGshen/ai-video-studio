<script setup lang="ts">
/**
 * 项目设置对话框（计划 M5 T12）：改这个项目的配音音色和语速（并试听）和思考强度。改完之后已经合成过的镜头
 * 会在叙事画布上显示「配音已过期」（timing 里记录了配音时的音色/语速，TD-36），重新配音即可。
 * 项目有一轮在跑时只读（后端也会拒绝，409）。留空表示用内置默认（音色 zizi、语速 1.0）。
 * 试听会真实调用 TTS，可能产生费用，对话框里写明。
 */
import { computed, ref, watch } from 'vue'
import { errorMessage } from '@/api/http'
import EffortSelect from '@/components/EffortSelect.vue'
import VoicePreviewButton from '@/components/VoicePreviewButton.vue'
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
import {
  usePatchProjectSettingsMutation,
  useProjectQuery,
  useVoicesQuery,
} from '@/composables/queries'
import { DEFAULT_EFFORT, effortFromSettings, type Effort } from '@/composables/effortChoice'
import { KIND_SUMMARY } from '@/composables/videoKindChoice'
import { SPEED_MAX, SPEED_MIN, parseSpeed, speedError } from '@/composables/voiceRules'

const props = defineProps<{ projectId: string }>()
const open = defineModel<boolean>('open', { default: false })

const { data: project } = useProjectQuery(() => props.projectId)
const { data: voices } = useVoicesQuery()
const patch = usePatchProjectSettingsMutation(() => props.projectId)

const voice = ref('')
const speedText = ref('')
const effort = ref<Effort>(DEFAULT_EFFORT)

watch(open, (isOpen) => {
  if (!isOpen) return
  const settings = project.value?.settings ?? {}
  voice.value = typeof settings.voice === 'string' ? settings.voice : ''
  speedText.value = typeof settings.speech_rate === 'number' ? String(settings.speech_rate) : ''
  effort.value = effortFromSettings(settings)
  patch.reset()
})

const busy = computed(() => project.value?.busy ?? false)
/** 留空表示清除（用内置默认）；有内容时必须合法。 */
const speedProblem = computed(() => (speedText.value.trim() === '' ? null : speedError(speedText.value)))
const previewVoice = computed(() => voice.value || 'zizi')
const previewSpeed = computed(() =>
  speedText.value.trim() === '' ? 1 : parseSpeed(speedText.value),
)
const error = computed(() => (patch.error.value ? errorMessage(patch.error.value) : null))

async function save(): Promise<void> {
  if (speedProblem.value) return
  try {
    await patch.mutateAsync({
      voice: voice.value === '' ? null : voice.value,
      speech_rate: speedText.value.trim() === '' ? null : parseSpeed(speedText.value),
      effort: effort.value,
    })
    open.value = false
  } catch {
    // 错误显示在对话框里（error）。
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>项目设置</DialogTitle>
        <DialogDescription>
          配音用的音色和语速，以及 agent 的思考强度（下一轮对话起生效）。改配音后已合成的镜头会显示「配音已过期」，回到叙事阶段重新配音即可。
        </DialogDescription>
      </DialogHeader>

      <p
        v-if="busy"
        class="text-sm text-amber-600"
      >
        项目正在运行一轮对话，结束后才能修改。
      </p>

      <div class="flex flex-col gap-3">
        <div
          v-if="project"
          class="flex flex-col gap-0.5 text-sm"
          data-testid="project-kind"
        >
          <span class="text-muted-foreground text-xs">视频类型</span>
          <span>{{ KIND_SUMMARY(project.kind) }}</span>
          <span class="text-muted-foreground text-xs">创建后不能修改，换类型请新建项目</span>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="project-voice">音色</Label>
          <select
            id="project-voice"
            v-model="voice"
            class="border-input bg-background h-9 rounded-md border px-2 text-sm disabled:opacity-60"
            :disabled="busy"
            data-testid="project-voice"
          >
            <option value="">
              未设置（用内置默认 zizi）
            </option>
            <option
              v-for="item in voices"
              :key="item.alias"
              :value="item.alias"
            >
              {{ item.label }}（{{ item.alias }}）
            </option>
          </select>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="project-speed">语速（{{ SPEED_MIN }}–{{ SPEED_MAX }}，留空用 1.0）</Label>
          <Input
            id="project-speed"
            v-model="speedText"
            class="w-32"
            inputmode="decimal"
            :disabled="busy"
            data-testid="project-speed"
          />
          <p
            v-if="speedProblem"
            class="text-destructive text-xs"
          >
            {{ speedProblem }}
          </p>
        </div>
        <div class="flex items-center gap-3">
          <VoicePreviewButton
            :voice="previewVoice"
            :speed="previewSpeed"
          />
          <span class="text-xs text-amber-600">试听会调用 TTS，可能产生费用</span>
        </div>
        <EffortSelect
          id="project-effort"
          v-model="effort"
          :disabled="busy"
        />
        <p
          v-if="error"
          class="text-destructive text-sm"
        >
          保存失败：{{ error }}
        </p>
      </div>

      <DialogFooter>
        <Button
          variant="outline"
          @click="open = false"
        >
          取消
        </Button>
        <Button
          :disabled="busy || patch.isPending.value || speedProblem !== null"
          data-testid="save-project-settings"
          @click="save"
        >
          保存
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
