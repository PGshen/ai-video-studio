<script setup lang="ts">
/**
 * 「语音」子页（计划 M5 T12）：可用音色列表（中文名取自旧项目音色表）、试听、新项目默认音色/语速。
 * 音色可以新增（选豆包 v1/v2）和删除；被项目使用、是默认音色或最后一个音色删不掉，原因原样显示。
 * 默认值是创建项目时**复制**进项目的（决策 D5），之后与这里脱钩；项目里的音色/语速在工作台的
 * 「项目设置」里改。试听会真实调用 TTS，可能产生费用，页面上写明；同一音色+语速的试听有缓存。
 */
import { computed, ref, watch } from 'vue'
import { errorMessage } from '@/api/http'
import VoicePreviewButton from '@/components/VoicePreviewButton.vue'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useCreateVoiceMutation,
  useDeleteVoiceMutation,
  usePatchSettingsMutation,
  useSettingsQuery,
  useVoicesQuery,
} from '@/composables/queries'
import { SPEED_MAX, SPEED_MIN, parseSpeed, speedError } from '@/composables/voiceRules'
import type { VoiceCreate, VoiceOut } from '@/types/api'
import VoiceDialog from './VoiceDialog.vue'
import { engineLabel } from './voiceForm'

const { data: voices, isPending, error: loadError } = useVoicesQuery()
const { data: settings } = useSettingsQuery()
const patch = usePatchSettingsMutation()
const createMutation = useCreateVoiceMutation()
const deleteMutation = useDeleteVoiceMutation()

const defaultVoice = ref('')
const speedText = ref('1')
const saved = ref(false)

watch(
  settings,
  (value) => {
    if (!value) return
    defaultVoice.value = value.tts_default.voice
    speedText.value = String(value.tts_default.speech_rate)
  },
  { immediate: true },
)

const speed = computed(() => parseSpeed(speedText.value))
const speedProblem = computed(() => speedError(speedText.value))
const dirty = computed(
  () =>
    settings.value !== undefined &&
    (defaultVoice.value !== settings.value.tts_default.voice ||
      speed.value !== settings.value.tts_default.speech_rate),
)
const saveError = computed(() => (patch.error.value ? errorMessage(patch.error.value) : null))

async function saveDefaults(): Promise<void> {
  if (speed.value === null) return
  saved.value = false
  try {
    await patch.mutateAsync({ tts_default: { voice: defaultVoice.value, speech_rate: speed.value } })
    saved.value = true
  } catch {
    // 错误显示在按钮旁（saveError）。
  }
}

const createOpen = ref(false)
const createError = ref<string | null>(null)
const deleting = ref<VoiceOut | null>(null)
const deleteOpen = ref(false)
const deleteError = ref<string | null>(null)

function openCreate(): void {
  createError.value = null
  createOpen.value = true
}

async function create(body: VoiceCreate): Promise<void> {
  createError.value = null
  try {
    await createMutation.mutateAsync(body)
    createOpen.value = false
  } catch (error) {
    createError.value = errorMessage(error)
  }
}

function askDelete(voice: VoiceOut): void {
  deleting.value = voice
  deleteError.value = null
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleting.value) return
  try {
    await deleteMutation.mutateAsync(deleting.value.alias)
    deleteOpen.value = false
  } catch (error) {
    deleteError.value = errorMessage(error)
  }
}

function genderLabel(gender: string): string {
  return gender === 'male' ? '男声' : gender === 'female' ? '女声' : gender
}
</script>

<template>
  <section class="flex max-w-3xl flex-col gap-6">
    <div>
      <h2 class="text-lg font-medium">
        语音
      </h2>
      <p class="text-muted-foreground text-sm">
        叙事阶段用这些音色给旁白配音。默认值只影响之后新建的项目；已有项目在工作台的「项目设置」里改。
      </p>
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

    <template v-else>
      <div class="flex flex-col gap-3">
        <h3 class="font-medium">
          新项目的默认值
        </h3>
        <div class="flex flex-wrap items-end gap-4">
          <div class="flex flex-col gap-1.5">
            <Label for="default-voice">默认音色</Label>
            <select
              id="default-voice"
              v-model="defaultVoice"
              class="border-input bg-background h-9 w-56 rounded-md border px-2 text-sm"
              data-testid="default-voice"
            >
              <option
                v-for="voice in voices"
                :key="voice.alias"
                :value="voice.alias"
              >
                {{ voice.label }}（{{ voice.alias }}）
              </option>
            </select>
          </div>
          <div class="flex flex-col gap-1.5">
            <Label for="default-speed">默认语速（{{ SPEED_MIN }}–{{ SPEED_MAX }}）</Label>
            <Input
              id="default-speed"
              v-model="speedText"
              class="w-28"
              inputmode="decimal"
              data-testid="default-speed"
            />
          </div>
          <Button
            :disabled="!dirty || speed === null || patch.isPending.value"
            data-testid="save-voice-defaults"
            @click="saveDefaults"
          >
            保存默认值
          </Button>
          <span
            v-if="saved && !dirty"
            class="text-muted-foreground text-sm"
          >已保存</span>
        </div>
        <p
          v-if="speedProblem"
          class="text-destructive text-xs"
        >
          {{ speedProblem }}
        </p>
        <p
          v-if="saveError"
          class="text-destructive text-sm"
        >
          保存失败：{{ saveError }}
        </p>
      </div>

      <div class="flex flex-col gap-3">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="font-medium">
              可用音色
            </h3>
            <p class="text-sm text-amber-600">
              试听会调用 TTS，可能产生费用（同一音色和语速只合成一次，之后走缓存）。试听用上面的语速。
            </p>
          </div>
          <Button
            variant="outline"
            data-testid="add-voice"
            @click="openCreate"
          >
            新增音色
          </Button>
        </div>
        <div class="overflow-x-auto rounded-md border">
          <table class="w-full text-sm">
            <tbody>
              <tr
                v-for="voice in voices"
                :key="voice.alias"
                class="border-t first:border-t-0"
                :data-testid="`voice-${voice.alias}`"
              >
                <td class="px-3 py-2">
                  <span class="font-medium">{{ voice.label }}</span>
                  <span class="text-muted-foreground ml-2 font-mono text-xs">{{ voice.alias }}</span>
                </td>
                <td class="px-3 py-2">
                  <Badge variant="outline">
                    {{ genderLabel(voice.gender) }}
                  </Badge>
                  <Badge
                    class="ml-1"
                    variant="outline"
                    :data-testid="`engine-${voice.alias}`"
                  >
                    {{ engineLabel(voice.engine) }}
                  </Badge>
                  <Badge
                    v-if="voice.alias === settings?.tts_default.voice"
                    class="ml-1"
                    variant="secondary"
                  >
                    默认
                  </Badge>
                </td>
                <td class="px-3 py-2 text-right">
                  <div class="flex justify-end gap-2">
                    <VoicePreviewButton
                      :voice="voice.alias"
                      :speed="speed"
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      :data-testid="`delete-voice-${voice.alias}`"
                      @click="askDelete(voice)"
                    >
                      删除
                    </Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <VoiceDialog
      v-model:open="createOpen"
      :existing="voices ?? []"
      :pending="createMutation.isPending.value"
      :error="createError"
      @create="create"
    />

    <AlertDialog v-model:open="deleteOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除音色 {{ deleting?.label }}（{{ deleting?.alias }}）？</AlertDialogTitle>
          <AlertDialogDescription>
            删除后不能恢复（可以重新新增）。被项目使用、是新项目默认音色，或是最后一个音色的删不掉，会告诉你原因。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <p
          v-if="deleteError"
          class="text-destructive text-sm"
          data-testid="delete-voice-error"
        >
          {{ deleteError }}
        </p>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <!-- 不用 AlertDialogAction：它点击即关闭，失败（409）时看不到原因。 -->
          <Button
            :disabled="deleteMutation.isPending.value"
            data-testid="confirm-delete-voice"
            @click="confirmDelete"
          >
            确认删除
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>
