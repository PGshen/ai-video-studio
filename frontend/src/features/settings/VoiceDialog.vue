<script setup lang="ts">
/**
 * 新增音色的对话框（计划 tts-voice-management T4）。只能新增（改了 speaker id 会让已合成的配音
 * 和音色脱钩，要改就删了重建）。校验与转换在 `voiceForm.ts`；提交由面板调接口。
 * 版本（豆包 v1 / v2）决定调用哪个资源：选错版本会合成失败，所以单独列出并给出 id 的特征。
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
import type { VoiceCreate, VoiceOut } from '@/types/api'
import {
  VOICE_ENGINES,
  emptyVoiceForm,
  toVoiceCreate,
  validateVoiceForm,
  type VoiceFormErrors,
  type VoiceFormValues,
} from './voiceForm'

const props = defineProps<{
  existing: readonly VoiceOut[]
  pending?: boolean
  error?: string | null
}>()
const emit = defineEmits<{ (e: 'create', body: VoiceCreate): void }>()

const open = defineModel<boolean>('open', { default: false })
const values = ref<VoiceFormValues>(emptyVoiceForm())
const errors = ref<VoiceFormErrors>({})

const engineHint = computed(
  () => VOICE_ENGINES.find((item) => item.value === values.value.engine)?.hint ?? '',
)

watch(open, (isOpen) => {
  if (!isOpen) return
  values.value = emptyVoiceForm()
  errors.value = {}
})

function submit(): void {
  errors.value = validateVoiceForm(values.value, props.existing)
  if (Object.keys(errors.value).length > 0) return
  emit('create', toVoiceCreate(values.value))
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>新增音色</DialogTitle>
        <DialogDescription>
          填写火山引擎控制台里的音色 id，并选对它所属的豆包版本。新增后可以先试听再使用。
        </DialogDescription>
      </DialogHeader>

      <div class="grid grid-cols-2 gap-3">
        <div class="flex flex-col gap-1.5">
          <Label for="voice-label">名称</Label>
          <Input
            id="voice-label"
            v-model="values.label"
            placeholder="例如 清澈梓梓"
            data-testid="voice-label"
          />
          <p
            v-if="errors.label"
            class="text-destructive text-xs"
          >
            {{ errors.label }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="voice-alias">别名</Label>
          <Input
            id="voice-alias"
            v-model="values.alias"
            placeholder="例如 zizi"
            data-testid="voice-alias"
          />
          <p
            v-if="errors.alias"
            class="text-destructive text-xs"
          >
            {{ errors.alias }}
          </p>
        </div>
        <div class="col-span-2 flex flex-col gap-1.5">
          <Label for="voice-speaker">音色 id（speaker id）</Label>
          <Input
            id="voice-speaker"
            v-model="values.speaker_id"
            class="font-mono"
            placeholder="zh_female_qingchezizi_uranus_bigtts"
            data-testid="voice-speaker"
          />
          <p
            v-if="errors.speaker_id"
            class="text-destructive text-xs"
          >
            {{ errors.speaker_id }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="voice-engine">版本</Label>
          <select
            id="voice-engine"
            v-model="values.engine"
            class="border-input bg-background h-9 rounded-md border px-2 text-sm"
            data-testid="voice-engine"
          >
            <option
              v-for="item in VOICE_ENGINES"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </option>
          </select>
          <p class="text-muted-foreground text-xs">
            {{ engineHint }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="voice-gender">性别</Label>
          <select
            id="voice-gender"
            v-model="values.gender"
            class="border-input bg-background h-9 rounded-md border px-2 text-sm"
            data-testid="voice-gender"
          >
            <option value="female">
              女声
            </option>
            <option value="male">
              男声
            </option>
          </select>
        </div>
      </div>

      <p
        v-if="error"
        class="text-destructive text-sm"
        data-testid="voice-dialog-error"
      >
        {{ error }}
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
          data-testid="voice-submit"
          @click="submit"
        >
          新增
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
