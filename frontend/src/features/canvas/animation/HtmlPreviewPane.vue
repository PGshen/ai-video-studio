<script setup lang="ts">
/**
 * 实时预览标签（设计 §7.2）：一个沙盒 iframe 加传输控制。
 *
 * iframe 用 `sandbox="allow-scripts"`、不带 `allow-same-origin`，页面是不透明源，只通过
 * `postMessage` 通信（`htmlPreview/previewProtocol.ts`，只信任自己那个 iframe 窗口）。页面
 * 本身是 1920×1080 的画布，这里按容器宽度整体缩放。`meta.hash` 变了才重载 iframe；预览页报错
 * 只显示横幅，不影响编辑和成片。播放时钟见 `useHtmlPlayback`。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Pause, Play, Repeat } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { htmlPreviewUrl } from '@/api/endpoints'
import type { HtmlPreviewMeta } from '@/types/api'
import { parsePreviewMessage, seekMessage } from './htmlPreview/previewProtocol'
import { sectionTicks, shouldReloadPreview } from './htmlPreview/previewClock'
import { useHtmlPlayback } from './htmlPreview/useHtmlPlayback'

const FRAME_WIDTH = 1920
const FRAME_HEIGHT = 1080

const props = defineProps<{ projectId: string; meta: HtmlPreviewMeta }>()

const frame = ref<HTMLIFrameElement | null>(null)
const stage = ref<HTMLDivElement | null>(null)
const loadedHash = ref<string | null>(null)
const frameReady = ref(false)
const pageError = ref<string | null>(null)
const scale = ref(0.4)

const src = computed(() => (loadedHash.value === null ? '' : htmlPreviewUrl(props.projectId, loadedHash.value)))

function post(message: unknown): void {
  frame.value?.contentWindow?.postMessage(message, '*')
}

const playback = useHtmlPlayback({
  meta: () => props.meta,
  onSeek: (t) => {
    if (frameReady.value) post(seekMessage(t))
  },
})

watch(
  () => props.meta.hash,
  (hash) => {
    if (!shouldReloadPreview(loadedHash.value, hash)) return
    frameReady.value = false
    pageError.value = null
    loadedHash.value = hash
  },
  { immediate: true },
)

function onMessage(event: MessageEvent): void {
  const message = parsePreviewMessage(event, frame.value?.contentWindow)
  if (message === null) return
  if (message.type === 'ready') {
    frameReady.value = true
    pageError.value = null
    post(seekMessage(playback.t.value))
  } else {
    pageError.value = message.message
  }
}

let observer: ResizeObserver | null = null
onMounted(() => {
  window.addEventListener('message', onMessage)
  if (stage.value !== null && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(([entry]) => {
      if (entry !== undefined && entry.contentRect.width > 0) {
        scale.value = entry.contentRect.width / FRAME_WIDTH
      }
    })
    observer.observe(stage.value)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  observer?.disconnect()
})

const ticks = computed(() => sectionTicks(props.meta.sections, props.meta.duration))
const currentSection = computed(() => props.meta.sections[playback.currentIndex.value])

function formatTime(seconds: number): string {
  const whole = Math.max(0, seconds)
  const minutes = Math.floor(whole / 60)
  return `${minutes}:${(whole - minutes * 60).toFixed(1).padStart(4, '0')}`
}

function onScrub(event: Event): void {
  playback.seekTo(Number((event.target as HTMLInputElement).value))
}
</script>

<template>
  <div
    class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto"
    data-testid="html-preview-pane"
  >
    <div
      v-if="pageError"
      class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm"
      role="alert"
      data-testid="preview-error"
    >
      预览页出错：{{ pageError }}
    </div>

    <div
      ref="stage"
      class="relative w-full overflow-hidden rounded border bg-black"
      :style="{ height: `${FRAME_HEIGHT * scale}px` }"
    >
      <iframe
        v-if="src"
        ref="frame"
        :src="src"
        sandbox="allow-scripts"
        title="HTML 动画实时预览"
        class="absolute top-0 left-0 border-0"
        :style="{
          width: `${FRAME_WIDTH}px`,
          height: `${FRAME_HEIGHT}px`,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
        }"
      />
    </div>

    <div class="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        :aria-label="playback.playing.value ? '暂停' : '播放'"
        data-testid="preview-play"
        @click="playback.toggle()"
      >
        <Pause v-if="playback.playing.value" />
        <Play v-else />
      </Button>
      <Button
        size="sm"
        :variant="playback.loop.value ? 'default' : 'outline'"
        :aria-pressed="playback.loop.value"
        aria-label="循环当前镜头"
        data-testid="preview-loop"
        @click="playback.setLoop(!playback.loop.value)"
      >
        <Repeat />
      </Button>
      <span
        class="text-muted-foreground text-xs tabular-nums"
        data-testid="preview-time"
      >
        {{ formatTime(playback.t.value) }} / {{ formatTime(meta.duration) }}
      </span>
      <span class="text-muted-foreground ml-auto truncate text-xs">
        {{ currentSection?.label }}
      </span>
    </div>

    <div class="relative">
      <input
        type="range"
        class="w-full"
        min="0"
        :max="meta.duration"
        step="0.01"
        :value="playback.t.value"
        aria-label="播放进度"
        data-testid="preview-scrubber"
        @input="onScrub"
      >
      <span
        v-for="tick in ticks"
        :key="tick"
        class="bg-muted-foreground/60 pointer-events-none absolute top-0 h-full w-px"
        :style="{ left: `${tick}%` }"
        data-testid="preview-tick"
      />
    </div>

    <div class="flex flex-wrap gap-1">
      <button
        v-for="(section, index) in meta.sections"
        :key="section.id"
        type="button"
        class="rounded px-2 py-1 text-xs whitespace-nowrap"
        :class="playback.currentIndex.value === index ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        data-testid="preview-section"
        @click="playback.jumpToSection(index)"
      >
        {{ section.label }}
      </button>
    </div>
  </div>
</template>
