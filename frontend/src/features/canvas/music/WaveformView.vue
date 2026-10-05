<script setup lang="ts">
/**
 * 波形包络加段落、事件与播放位置（SVG，不依赖 canvas，jsdom 里也能测）。坐标换算全在 `waveform.ts`。
 * 点击波形发出 `seek`（秒）。段落名放在波形上方的 HTML 条里，免得 `preserveAspectRatio="none"` 拉歪文字。
 */
import { computed, ref } from 'vue'
import type { MusicEventOut, MusicSectionOut } from '@/types/api'
import { eventMarkers, sectionBands, timeToX, waveformPeaks, xToTime } from './waveform'

const props = defineProps<{
  waveform: number[]
  duration: number
  sections: MusicSectionOut[]
  events: MusicEventOut[]
  currentTime: number
}>()
const emit = defineEmits<{ seek: [seconds: number] }>()

const WIDTH = 1000
const HEIGHT = 120

const svg = ref<SVGSVGElement | null>(null)
const bars = computed(() => waveformPeaks(props.waveform, WIDTH, HEIGHT))
const bands = computed(() => sectionBands(props.sections, props.duration, WIDTH))
const markers = computed(() => eventMarkers(props.events, props.duration, WIDTH))
const playheadX = computed(() => timeToX(props.currentTime, props.duration, WIDTH))

function onClick(event: MouseEvent): void {
  const rect = svg.value?.getBoundingClientRect()
  if (!rect || rect.width <= 0) return
  const x = ((event.clientX - rect.left) / rect.width) * WIDTH
  emit('seek', xToTime(x, props.duration, WIDTH))
}
</script>

<template>
  <div data-testid="waveform">
    <div class="text-muted-foreground relative h-5 text-xs">
      <span
        v-for="band in bands"
        :key="band.id"
        class="absolute top-0 truncate border-l pl-1"
        :style="{ left: `${(band.x / WIDTH) * 100}%`, width: `${(band.width / WIDTH) * 100}%` }"
        data-testid="waveform-section"
      >
        {{ band.label }}
      </span>
    </div>
    <svg
      ref="svg"
      :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
      preserveAspectRatio="none"
      class="bg-muted/30 h-28 w-full cursor-pointer rounded"
      role="img"
      aria-label="配乐波形，点击跳转"
      data-testid="waveform-svg"
      @click="onClick"
    >
      <rect
        v-for="band in bands"
        :key="band.id"
        :x="band.x"
        y="0"
        :width="band.width"
        :height="HEIGHT"
        class="fill-primary/5 stroke-border"
        stroke-width="1"
        vector-effect="non-scaling-stroke"
      />
      <rect
        v-for="(bar, index) in bars"
        :key="index"
        :x="bar.x"
        :y="bar.top"
        :width="bar.width"
        :height="Math.max(1, bar.bottom - bar.top)"
        class="fill-primary/70"
      />
      <template
        v-for="(marker, index) in markers"
        :key="`${marker.name}-${index}`"
      >
        <rect
          v-if="marker.kind === 'sweep'"
          :x="marker.x"
          y="0"
          :width="Math.max(1, marker.width)"
          :height="HEIGHT"
          class="fill-amber-500/20"
          data-testid="waveform-sweep"
        />
        <line
          v-else
          :x1="marker.x"
          :x2="marker.x"
          y1="0"
          :y2="HEIGHT"
          class="stroke-sky-500/60"
          stroke-width="1"
          vector-effect="non-scaling-stroke"
          data-testid="waveform-onset"
        />
      </template>
      <line
        :x1="playheadX"
        :x2="playheadX"
        y1="0"
        :y2="HEIGHT"
        class="stroke-destructive"
        stroke-width="2"
        vector-effect="non-scaling-stroke"
        data-testid="waveform-playhead"
      />
    </svg>
  </div>
</template>
