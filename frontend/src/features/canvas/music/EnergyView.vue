<script setup lang="ts">
/**
 * 导入音乐的能量曲线（SVG）：整曲能量条形，叠加拍线（细）与强拍线（粗）、段落色块与名称、
 * 截取区间外的遮罩和播放位置。点击曲线或段落名发出 `seek`（整曲秒）。坐标换算全在 `importView.ts`。
 */
import { computed, ref } from 'vue'
import type {
  MusicEnergyOut,
  MusicGridOut,
  MusicRangeOut,
  MusicSectionOut,
} from '@/types/api'
import { energyBars, gridLines, rangeMask, sectionBandsFromMeta } from './importView'
import { timeToX, xToTime } from './waveform'

const props = defineProps<{
  energy: MusicEnergyOut | null
  grid: MusicGridOut | null
  range: MusicRangeOut | null
  sections: MusicSectionOut[]
  duration: number
  currentTime: number
}>()
const emit = defineEmits<{ seek: [seconds: number] }>()

const WIDTH = 1000
const HEIGHT = 120

const svg = ref<SVGSVGElement | null>(null)
const bars = computed(() => (props.energy ? energyBars(props.energy, WIDTH, HEIGHT) : []))
const lines = computed(() =>
  props.grid ? gridLines(props.grid, props.range, props.duration, WIDTH) : [],
)
const bands = computed(() => sectionBandsFromMeta(props.sections, props.duration, WIDTH))
const mask = computed(() => rangeMask(props.range, props.duration, WIDTH))
const playheadX = computed(() => timeToX(props.currentTime, props.duration, WIDTH))

function onClick(event: MouseEvent): void {
  const rect = svg.value?.getBoundingClientRect()
  if (!rect || rect.width <= 0) return
  emit('seek', xToTime(((event.clientX - rect.left) / rect.width) * WIDTH, props.duration, WIDTH))
}

function sectionStart(id: string): number {
  return props.sections.find((s) => s.id === id)?.start ?? 0
}
</script>

<template>
  <div data-testid="energy-view">
    <div class="text-muted-foreground relative h-5 text-xs">
      <button
        v-for="band in bands"
        :key="band.id"
        type="button"
        class="hover:text-foreground absolute top-0 truncate border-l pl-1 text-left"
        :style="{ left: `${(band.x / WIDTH) * 100}%`, width: `${(band.width / WIDTH) * 100}%` }"
        data-testid="energy-section"
        @click="emit('seek', sectionStart(band.id))"
      >
        {{ band.label }}
      </button>
    </div>
    <svg
      ref="svg"
      :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
      preserveAspectRatio="none"
      class="bg-muted/30 h-28 w-full cursor-pointer rounded"
      role="img"
      aria-label="能量曲线，点击跳转"
      data-testid="energy-svg"
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
        class="fill-primary/60"
      />
      <line
        v-for="(line, index) in lines"
        :key="`g${index}`"
        :x1="line.x"
        :x2="line.x"
        y1="0"
        :y2="HEIGHT"
        :class="line.strong ? 'stroke-sky-500/80' : 'stroke-sky-500/30'"
        :stroke-width="line.strong ? 2 : 1"
        vector-effect="non-scaling-stroke"
        :data-testid="line.strong ? 'energy-downbeat' : 'energy-beat'"
      />
      <template v-if="mask">
        <rect
          :x="mask.left.x"
          y="0"
          :width="mask.left.width"
          :height="HEIGHT"
          class="fill-background/70"
          data-testid="energy-mask-left"
        />
        <rect
          :x="mask.right.x"
          y="0"
          :width="mask.right.width"
          :height="HEIGHT"
          class="fill-background/70"
          data-testid="energy-mask-right"
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
        data-testid="energy-playhead"
      />
    </svg>
  </div>
</template>
