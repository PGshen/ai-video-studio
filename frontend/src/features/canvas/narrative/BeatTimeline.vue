<script setup lang="ts">
/**
 * 镜头配音播放条（M3 T10）：一个 `<audio>` + 按 beat 起止时间分段的刻度条。
 * 点某一段跳到该 beat 的开始时间播放；播放中当前所在的 beat 高亮。
 * 音频文件走通用的工作区文件端点（`workspaceFileUrl`），不需要新增端点。
 *
 * 那个端点不支持 HTTP Range，浏览器把这样的音频当成"不可跳转"，设
 * `currentTime` 会被忽略（L4 走查实测）。所以这里先把音频整个取成 blob，
 * 再用 `URL.createObjectURL` 给 `<audio>`：一个镜头的配音只有几十到几百
 * KB，比给端点加 Range 支持（会改公共接口）合适。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { NarrativeBeat } from './narrativeDoc'
import type { BeatTiming } from './timingStatus'

const props = defineProps<{
  audioUrl: string
  durationSeconds: number
  timings: BeatTiming[]
  beats: NarrativeBeat[]
}>()

const audioRef = ref<HTMLAudioElement | null>(null)
const currentSeconds = ref(0)
const objectUrl = ref<string | null>(null)
const loadError = ref<string | null>(null)

function releaseObjectUrl(): void {
  if (objectUrl.value !== null) URL.revokeObjectURL(objectUrl.value)
  objectUrl.value = null
}

watch(
  () => props.audioUrl,
  async (url) => {
    releaseObjectUrl()
    loadError.value = null
    currentSeconds.value = 0
    try {
      const response = await fetch(url)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const blob = await response.blob()
      // 加载期间又切换了镜头：丢弃这次的结果。
      if (url !== props.audioUrl) return
      objectUrl.value = URL.createObjectURL(blob)
    } catch (error) {
      if (url === props.audioUrl) {
        loadError.value = error instanceof Error ? error.message : String(error)
      }
    }
  },
  { immediate: true },
)

onBeforeUnmount(releaseObjectUrl)

const segments = computed(() => {
  const total = props.durationSeconds > 0 ? props.durationSeconds : 1
  return props.timings.map((timing, index) => ({
    index,
    start: timing.start_seconds,
    end: timing.end_seconds,
    left: Math.min(100, (timing.start_seconds / total) * 100),
    width: Math.max(0, ((timing.end_seconds - timing.start_seconds) / total) * 100),
    cue: props.beats[index]?.cue_text ?? '',
  }))
})

const activeIndex = computed(
  () =>
    segments.value.find((s) => currentSeconds.value >= s.start && currentSeconds.value < s.end)
      ?.index ?? -1,
)

function onTimeUpdate(): void {
  currentSeconds.value = audioRef.value?.currentTime ?? 0
}

async function seekTo(start: number): Promise<void> {
  const audio = audioRef.value
  if (audio === null) return
  audio.currentTime = start
  try {
    await audio.play()
  } catch {
    // 浏览器拒绝自动播放（没有用户手势）时忽略：进度条已经跳过去了。
  }
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <p
      v-if="loadError"
      class="text-destructive text-xs"
    >
      音频加载失败：{{ loadError }}
    </p>
    <audio
      v-else-if="objectUrl"
      ref="audioRef"
      class="w-full"
      controls
      preload="metadata"
      :src="objectUrl"
      @timeupdate="onTimeUpdate"
    />
    <p
      v-else
      class="text-muted-foreground text-xs"
    >
      音频加载中…
    </p>
    <div
      v-if="segments.length > 0"
      class="bg-muted relative h-7 w-full overflow-hidden rounded"
      data-testid="beat-timeline"
    >
      <button
        v-for="segment in segments"
        :key="segment.index"
        type="button"
        class="absolute top-0 h-full truncate border-r px-1 text-left text-xs"
        :class="segment.index === activeIndex ? 'bg-primary text-primary-foreground' : 'hover:bg-primary/20'"
        :style="{ left: `${segment.left}%`, width: `${segment.width}%` }"
        :title="`beat ${segment.index + 1}：${segment.start.toFixed(2)}s – ${segment.end.toFixed(2)}s`"
        @click="seekTo(segment.start)"
      >
        {{ segment.index + 1 }} {{ segment.cue }}
      </button>
    </div>
    <p class="text-muted-foreground text-xs">
      时长 {{ durationSeconds.toFixed(2) }}s · 点击分段可跳到对应 beat
    </p>
  </div>
</template>
