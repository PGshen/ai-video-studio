<script setup lang="ts">
/**
 * 创建项目时的视频类型选择器（计划 pipeline-config T6）：四张预设卡片 + 配乐下拉 + 所选配置的流水线。
 * 所有可用性和流水线都来自后端的 `data`（`GET /api/video-kinds`），这里不复写规则。
 * 调用方用 `composables/videoKindChoice.ts::initialSelection` 设置初始值。
 */
import { computed } from 'vue'
import { Label } from '@/components/ui/label'
import {
  MUSIC_LABELS,
  findKind,
  pipelineText,
  presetAvailability,
} from '@/composables/videoKindChoice'
import type { MusicSource, VideoKind, VideoKindsOut } from '@/types/api'

const props = defineProps<{ data: VideoKindsOut }>()
const videoKind = defineModel<VideoKind>('videoKind', { required: true })
const music = defineModel<MusicSource>('music', { required: true })

const cards = computed(() =>
  props.data.presets.map((preset) => ({ preset, ...presetAvailability(props.data, preset) })),
)
const current = computed(() => props.data.presets.find((p) => p.video_kind === videoKind.value))
const selected = computed(() =>
  current.value ? findKind(props.data.kinds, current.value, music.value) : undefined,
)
const musicOptions = computed(() =>
  (current.value?.music_choices ?? []).map((value) => {
    const kind = current.value ? findKind(props.data.kinds, current.value, value) : undefined
    const available = kind?.available ?? false
    return {
      value,
      available,
      label: available
        ? MUSIC_LABELS[value]
        : `${MUSIC_LABELS[value]}（${kind?.unavailable_reason ?? '暂不可用'}）`,
      title: kind?.unavailable_reason ?? undefined,
    }
  }),
)

function choose(preset: (typeof cards.value)[number]): void {
  if (!preset.available) return
  videoKind.value = preset.preset.video_kind
  const options = preset.preset.music_choices.map((m) => ({
    m,
    kind: findKind(props.data.kinds, preset.preset, m),
  }))
  // 保持当前配乐（如果新预设也有且可用），否则取第一个可用的。
  const keep = options.find((o) => o.m === music.value && o.kind?.available)
  music.value = (keep ?? options.find((o) => o.kind?.available) ?? options[0]).m
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <Label>视频类型</Label>
    <div class="grid grid-cols-2 gap-2">
      <div
        v-for="card in cards"
        :key="card.preset.video_kind"
        class="flex flex-col gap-1"
      >
        <button
          type="button"
          class="border-input hover:bg-accent flex h-full flex-col gap-0.5 rounded-md border p-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
          :class="card.preset.video_kind === videoKind ? 'border-primary ring-primary ring-1' : ''"
          :disabled="!card.available"
          :aria-pressed="card.preset.video_kind === videoKind"
          :data-testid="`kind-card-${card.preset.video_kind}`"
          @click="choose(card)"
        >
          <span class="font-medium">{{ card.preset.label }}</span>
          <span class="text-muted-foreground text-xs">{{ card.preset.description }}</span>
        </button>
        <p
          v-if="!card.available"
          class="text-muted-foreground text-xs"
          :data-testid="`kind-reason-${card.preset.video_kind}`"
        >
          {{ card.reason ?? '暂不可用' }}
        </p>
      </div>
    </div>

    <template v-if="current && current.music_choices.length > 1">
      <Label for="video-kind-music">配乐</Label>
      <select
        id="video-kind-music"
        v-model="music"
        class="border-input bg-background h-9 rounded-md border px-2 text-sm"
        data-testid="music-select"
      >
        <option
          v-for="option in musicOptions"
          :key="option.value"
          :value="option.value"
          :disabled="!option.available"
          :title="option.title"
        >
          {{ option.label }}
        </option>
      </select>
    </template>

    <p
      v-if="selected"
      class="text-muted-foreground text-xs"
      data-testid="kind-pipeline"
    >
      流水线：{{ pipelineText(selected.pipeline) }}
    </p>
  </div>
</template>
