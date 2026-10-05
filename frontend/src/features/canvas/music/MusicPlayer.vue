<script setup lang="ts">
/**
 * 配乐的"播放"标签：播放器、波形（点击跳转）、指标摘要和分析图。音色、和声、混响量与声像无法由
 * 指标判断，这里固定提示用户试听。`seek` 对外暴露，事件表点击时用它跳转。
 */
import { computed, ref } from 'vue'
import { musicAudioUrl, workspaceFileUrl } from '@/api/endpoints'
import type { MusicMetaOut } from '@/types/api'
import WaveformView from './WaveformView.vue'
import { formatClock, matchRows, metricRows, metricWarnings } from './musicView'

const props = defineProps<{ projectId: string; meta: MusicMetaOut }>()

const audio = ref<HTMLAudioElement | null>(null)
const currentTime = ref(0)
const duration = computed(() => props.meta.duration ?? 0)
const src = computed(() => musicAudioUrl(props.projectId, props.meta.hash))
const pictureUrl = computed(() =>
  workspaceFileUrl(props.projectId, 'music/analysis.png', props.meta.hash ?? undefined),
)

function onTimeUpdate(): void {
  currentTime.value = audio.value?.currentTime ?? 0
}

function seek(seconds: number): void {
  const el = audio.value
  if (el) el.currentTime = seconds
  currentTime.value = seconds
}
defineExpose({ seek })
</script>

<template>
  <div
    class="grid min-h-0 content-start gap-3 overflow-y-auto"
    data-testid="music-player"
  >
    <audio
      ref="audio"
      :src="src"
      controls
      preload="metadata"
      class="w-full"
      data-testid="music-audio"
      @timeupdate="onTimeUpdate"
      @seeked="onTimeUpdate"
    />
    <WaveformView
      :waveform="meta.waveform"
      :duration="duration"
      :sections="meta.sections"
      :events="meta.events"
      :current-time="currentTime"
      @seek="seek"
    />
    <p class="text-muted-foreground text-xs tabular-nums">
      {{ formatClock(currentTime) }} / {{ formatClock(duration) }}
      <template v-if="meta.bpm">
        · {{ meta.bpm }} BPM
      </template>
    </p>

    <dl
      class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm"
      data-testid="music-metrics"
    >
      <template
        v-for="row in metricRows(meta.metrics)"
        :key="row.label"
      >
        <dt class="text-muted-foreground">
          {{ row.label }}
        </dt>
        <dd class="tabular-nums">
          {{ row.value }}
        </dd>
      </template>
    </dl>
    <p
      v-if="matchRows(meta.metrics).length > 0"
      class="text-xs"
    >
      事件匹配：
      <span
        v-for="row in matchRows(meta.metrics)"
        :key="row.name"
        class="mr-2"
      >{{ row.name }} {{ row.matched }}/{{ row.detectable }}</span>
    </p>
    <ul
      v-if="metricWarnings(meta.metrics).length > 0"
      class="list-disc pl-5 text-xs"
      data-testid="music-warnings"
    >
      <li
        v-for="(warning, index) in metricWarnings(meta.metrics)"
        :key="index"
      >
        {{ warning }}
      </li>
    </ul>

    <p
      class="text-muted-foreground rounded border px-3 py-2 text-xs"
      data-testid="listen-note"
    >
      这些指标只能说明节奏对齐、响度和结构；音色、和声、混响量与声像它们判断不了，请用上面的播放器试听。
    </p>

    <img
      :src="pictureUrl"
      alt="配乐分析图：波形、谱图、能量与起音"
      class="w-full rounded border"
      data-testid="music-picture"
    >
  </div>
</template>
