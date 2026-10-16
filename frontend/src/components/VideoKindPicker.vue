<script setup lang="ts">
/**
 * 创建项目时的视频类型选择器（计划 pipeline-config T6；free-mode T8 加了自由模式）：预设卡片 + 配乐下拉 +
 * 所选配置的流水线。所有可用性和流水线都来自后端的 `data`（`GET /api/video-kinds`），这里不复写规则。
 *
 * 预设用 `presetKey` 区分（分阶段与自由各有一个同 `video_kind` 的预设）；`modes` 只保留给定模式的预设，
 * 两种模式都在时分成「分阶段」「自由」两组。调用方用 `composables/videoKindChoice.ts::initialSelection`
 * （对 `presetsFor(data, modes)` 调用）设置初始值。
 */
import { computed } from 'vue'
import { Label } from '@/components/ui/label'
import {
  MUSIC_LABELS,
  findKind,
  pipelineText,
  presetAvailability,
  presetKey,
  presetsFor,
} from '@/composables/videoKindChoice'
import type { Mode, MusicSource, PresetOut, VideoKindsOut } from '@/types/api'

const props = withDefaults(defineProps<{ data: VideoKindsOut; modes?: Mode[] }>(), {
  modes: () => ['staged', 'free', 'open'],
})
const preset = defineModel<string>('preset', { required: true })
const music = defineModel<MusicSource>('music', { required: true })

const GROUP_LABELS: Record<Mode, string> = {
  staged: '分阶段（选题 → 叙事 → 动画，逐步定稿）',
  free: '自由（一个对话里完成全部，不分阶段）',
  open: '完全自由（没有结构和检查，直接在工作区里创作）',
}

const scoped = computed(() => presetsFor(props.data, props.modes))
const groups = computed(() =>
  props.modes
    .map((mode) => ({
      mode,
      cards: scoped.value.presets
        .filter((p) => p.default.mode === mode)
        .map((p) => ({ preset: p, key: presetKey(p), ...presetAvailability(scoped.value, p) })),
    }))
    .filter((group) => group.cards.length > 0),
)
const grouped = computed(() => groups.value.length > 1)
const current = computed(() => scoped.value.presets.find((p) => presetKey(p) === preset.value))
const selected = computed(() =>
  current.value ? findKind(scoped.value.kinds, current.value, music.value) : undefined,
)
const musicOptions = computed(() =>
  (current.value?.music_choices ?? []).map((value) => {
    const kind = current.value ? findKind(scoped.value.kinds, current.value, value) : undefined
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

function choose(card: { preset: PresetOut; key: string; available: boolean }): void {
  if (!card.available) return
  preset.value = card.key
  const options = card.preset.music_choices.map((m) => ({
    m,
    kind: findKind(scoped.value.kinds, card.preset, m),
  }))
  // 保持当前配乐（如果新预设也有且可用），否则取第一个可用的。
  const keep = options.find((o) => o.m === music.value && o.kind?.available)
  music.value = (keep ?? options.find((o) => o.kind?.available) ?? options[0]).m
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <Label>视频类型</Label>
    <div
      v-for="group in groups"
      :key="group.mode"
      class="flex flex-col gap-1"
    >
      <p
        v-if="grouped"
        class="text-muted-foreground text-xs"
        :data-testid="`kind-group-${group.mode}`"
      >
        {{ GROUP_LABELS[group.mode] }}
      </p>
      <div class="grid grid-cols-2 gap-2">
        <div
          v-for="card in group.cards"
          :key="card.key"
          class="flex flex-col gap-1"
        >
          <button
            type="button"
            class="border-input hover:bg-accent flex h-full flex-col gap-0.5 rounded-md border p-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
            :class="card.key === preset ? 'border-primary ring-primary ring-1' : ''"
            :disabled="!card.available"
            :aria-pressed="card.key === preset"
            :data-testid="`kind-card-${card.key}`"
            @click="choose(card)"
          >
            <span class="font-medium">{{ card.preset.label }}</span>
            <span class="text-muted-foreground text-xs">{{ card.preset.description }}</span>
          </button>
          <p
            v-if="!card.available"
            class="text-muted-foreground text-xs"
            :data-testid="`kind-reason-${card.key}`"
          >
            {{ card.reason ?? '暂不可用' }}
          </p>
        </div>
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
