<script setup lang="ts">
/**
 * 「创建项目」对话框（计划 M4 T9）：标题预填卡片标题，可以改；成功后跳到新项目的当前阶段。
 * 创建成功后 `useCreateProjectMutation` 会让选题池和项目列表的查询失效（卡片上的项目数 +1）。
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
import EffortSelect from '@/components/EffortSelect.vue'
import StyleSelect from '@/components/StyleSelect.vue'
import VideoKindPicker from '@/components/VideoKindPicker.vue'
import { useCreateProjectMutation, useStylesQuery, useVideoKindsQuery } from '@/composables/queries'
import { DEFAULT_EFFORT, type Effort } from '@/composables/effortChoice'
import { initialStyleId, styleIdForRequest } from '@/composables/styleChoice'
import { findKind, initialSelection } from '@/composables/videoKindChoice'
import type { IdeaOut, MusicSource, VideoKind } from '@/types/api'

const props = defineProps<{ idea: IdeaOut | null }>()
const open = defineModel<boolean>('open', { default: false })

const router = useRouter()
const mutation = useCreateProjectMutation()
const { data: stylePresets } = useStylesQuery()
const { data: videoKinds, isError: kindsError } = useVideoKindsQuery()
const videoKind = ref<VideoKind>('explainer_manim')
const music = ref<MusicSource>('none')
const title = ref('')
const styleId = ref('')
const effort = ref<Effort>(DEFAULT_EFFORT)

watch(open, (isOpen) => {
  if (isOpen) {
    title.value = props.idea?.title ?? ''
    styleId.value = initialStyleId(stylePresets.value ?? [])
    effort.value = DEFAULT_EFFORT
    resetKind()
    mutation.reset()
  }
})

function resetKind(): void {
  if (!videoKinds.value) return
  const initial = initialSelection(videoKinds.value)
  videoKind.value = initial.videoKind
  music.value = initial.music
}
// 对话框打开时类型数据可能还没到：到了之后补上预选。
watch(videoKinds, (data, old) => {
  if (data && !old) resetKind()
})

const selectedKind = computed(() => {
  const data = videoKinds.value
  const preset = data?.presets.find((p) => p.video_kind === videoKind.value)
  return data && preset ? findKind(data.kinds, preset, music.value) : undefined
})
const canSubmit = computed(() => selectedKind.value?.available === true)

async function submit(): Promise<void> {
  const trimmed = title.value.trim()
  const kind = selectedKind.value
  if (!trimmed || !props.idea || !kind?.available) return
  const project = await mutation.mutateAsync({
    title: trimmed,
    idea_id: props.idea.id,
    style_preset_id: styleIdForRequest(styleId.value),
    engine: kind.engine,
    narration: kind.narration,
    music_source: kind.music_source,
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
        <DialogTitle>用这张卡片创建项目</DialogTitle>
        <DialogDescription>
          项目会进入所选类型的第一个阶段，卡片内容会作为起点带过去；卡片随后变为「已创建项目」。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-2">
        <Label for="create-project-title">项目标题</Label>
        <Input
          id="create-project-title"
          v-model="title"
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
          v-model:video-kind="videoKind"
          v-model:music="music"
          class="mt-2"
          :data="videoKinds"
        />
        <StyleSelect
          id="create-project-style"
          v-model="styleId"
          class="mt-2"
          :presets="stylePresets ?? []"
        />
        <EffortSelect
          id="create-project-effort"
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
          :disabled="!title.trim() || !canSubmit || mutation.isPending.value"
          @click="submit"
        >
          {{ mutation.isPending.value ? '创建中…' : '创建项目' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
