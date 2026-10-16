<script setup lang="ts">
/**
 * 项目页「新建项目」对话框（free-mode 设计 §6.1）：直接创建自由项目，不经过选题池。
 * 只列自由模式的三种形态（自由讲解可选是否带背景乐）和「完全自由」（open-mode：只填主题）；
 * 多阶段项目仍从选题卡创建。
 * 成功后跳到新项目唯一的阶段；音色/语速由后端从默认值复制，这里不管。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
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
import { Textarea } from '@/components/ui/textarea'
import EffortSelect from '@/components/EffortSelect.vue'
import StyleSelect from '@/components/StyleSelect.vue'
import VideoKindPicker from '@/components/VideoKindPicker.vue'
import { useCreateProjectMutation, useStylesQuery, useVideoKindsQuery } from '@/composables/queries'
import { DEFAULT_EFFORT, type Effort } from '@/composables/effortChoice'
import { initialStyleId, styleIdForRequest } from '@/composables/styleChoice'
import {
  initialSelection,
  kindFields,
  presetsFor,
  selectedKind as kindFor,
} from '@/composables/videoKindChoice'
import type { Mode, MusicSource } from '@/types/api'

const open = defineModel<boolean>('open', { default: false })

const MODES: Mode[] = ['free', 'open']
const THEME_MAX_CHARS = 2000

const router = useRouter()
const mutation = useCreateProjectMutation()
const { data: stylePresets } = useStylesQuery()
const { data: videoKinds, isError: kindsError } = useVideoKindsQuery()
const freeKinds = computed(() => (videoKinds.value ? presetsFor(videoKinds.value, MODES) : undefined))
const preset = ref('free-explainer_html')
const music = ref<MusicSource>('none')
const title = ref('')
const theme = ref('')
const styleId = ref('')
const effort = ref<Effort>(DEFAULT_EFFORT)

watch(open, (isOpen) => {
  if (isOpen) {
    title.value = ''
    theme.value = ''
    styleId.value = initialStyleId(stylePresets.value ?? [])
    effort.value = DEFAULT_EFFORT
    resetKind()
    mutation.reset()
  }
})

function resetKind(): void {
  if (!freeKinds.value || freeKinds.value.presets.length === 0) return
  const initial = initialSelection(freeKinds.value)
  preset.value = initial.preset
  music.value = initial.music
}
// 对话框打开时类型数据可能还没到：到了之后补上预选。
watch(videoKinds, (data, old) => {
  if (data && !old) resetKind()
})

const selectedKind = computed(() =>
  freeKinds.value ? kindFor(freeKinds.value, preset.value, music.value) : undefined,
)
const isOpenMode = computed(() => selectedKind.value?.mode === 'open')
const canSubmit = computed(
  () => !kindsError.value && selectedKind.value?.available === true && title.value.trim() !== '',
)

async function submit(): Promise<void> {
  const kind = selectedKind.value
  if (!canSubmit.value || !kind) return
  const trimmedTheme = theme.value.trim()
  const project = await mutation.mutateAsync({
    title: title.value.trim(),
    style_preset_id: styleIdForRequest(styleId.value),
    ...kindFields(kind),
    ...(kind.mode === 'open' && trimmedTheme ? { theme: trimmedTheme } : {}),
    settings: { effort: effort.value },
  })
  open.value = false
  await router.push(`/projects/${project.id}/${project.current_stage}`)
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>新建项目</DialogTitle>
        <DialogDescription>
          自由模式：不经过选题和阶段，在一个对话里完成写稿、配乐、画面，随时预览和出成片；
          完全自由：没有任何结构和检查，像直接用 Claude Code 一样在工作区里创作。
          需要逐步打磨的项目，请从「选题」里的卡片创建。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-2">
        <Label for="new-free-project-title">项目标题</Label>
        <Input
          id="new-free-project-title"
          v-model="title"
          placeholder="例如：为什么天空是蓝色的"
          @keydown.enter="submit"
        />
        <p
          v-if="kindsError"
          class="text-destructive mt-2 text-sm"
          data-testid="video-kinds-error"
        >
          视频类型加载失败，暂时不能创建项目，请稍后重试。
        </p>
        <VideoKindPicker
          v-else-if="videoKinds"
          v-model:preset="preset"
          v-model:music="music"
          class="mt-2"
          :data="videoKinds"
          :modes="MODES"
        />
        <template v-if="isOpenMode">
          <Label
            for="new-free-project-theme"
            class="mt-2"
          >主题（可选，写进 project.md）</Label>
          <Textarea
            id="new-free-project-theme"
            v-model="theme"
            :maxlength="THEME_MAX_CHARS"
            rows="4"
            placeholder="例如：用 10 秒的动画讲清楚光为什么会折射，给中学生看"
          />
        </template>
        <StyleSelect
          id="new-free-project-style"
          v-model="styleId"
          class="mt-2"
          :presets="stylePresets ?? []"
        />
        <EffortSelect
          id="new-free-project-effort"
          v-model="effort"
          class="mt-2"
        />
        <p
          v-if="mutation.isError.value"
          class="text-destructive text-sm"
        >
          创建失败：{{ (mutation.error.value as Error)?.message }}
        </p>
      </div>
      <DialogFooter>
        <Button
          :disabled="!canSubmit || mutation.isPending.value"
          @click="submit"
        >
          {{ mutation.isPending.value ? '创建中…' : '创建项目' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
