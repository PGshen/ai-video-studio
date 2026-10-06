<script setup lang="ts">
/**
 * 实时预览标签（设计 §7.2）：一个沙盒 iframe 加传输控制。
 *
 * iframe 用 `sandbox="allow-scripts"`、不带 `allow-same-origin`，页面是不透明源，只通过
 * `postMessage` 通信（`htmlPreview/previewProtocol.ts`，只信任自己那个 iframe 窗口）。不透明源的
 * iframe 对本机服务的请求会被浏览器拦下（内置浏览器里实测：连它自己的页面和脚本都取不到），所以
 * 页面由本组件取成自包含的 HTML 文本，设为 `srcdoc`。页面本身是 1920×1080 的画布，这里按容器宽度
 * 整体缩放。`meta.hash` 变了才重新取页面；预览页报错只显示横幅，不影响编辑和成片。播放时钟见
 * `useHtmlPlayback`。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Pause, Play, Repeat, Volume2, VolumeX } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { getHtmlPreviewPage } from '@/api/endpoints'
import type { HtmlPreviewMeta } from '@/types/api'
import { parsePreviewMessage, seekMessage } from './htmlPreview/previewProtocol'
import { sectionTicks, shouldReloadPreview } from './htmlPreview/previewClock'
import { useHtmlPlayback } from './htmlPreview/useHtmlPlayback'

const FRAME_WIDTH = 1920
const FRAME_HEIGHT = 1080
const FPS = 30

const props = defineProps<{
  projectId: string
  meta: HtmlPreviewMeta
  /** 项目有配乐，但配乐还没渲染或与当前文件对不上（`meta.music` 为空）：提示重新渲染。 */
  scoreMissing?: boolean
}>()

const frame = ref<HTMLIFrameElement | null>(null)
const stage = ref<HTMLDivElement | null>(null)
const loadedHash = ref<string | null>(null)
const pageHtml = ref<string | null>(null)
const frameReady = ref(false)
const pageError = ref<string | null>(null)
const scale = ref(0.4)

function post(message: unknown): void {
  frame.value?.contentWindow?.postMessage(message, '*')
}

/** 页面只在 `t < 镜头末尾` 时画镜头，`t = 总时长` 会是一帧黑；和成片一样，最后一帧取 `(N-1)/fps`。 */
function pageTime(t: number): number {
  return Math.min(t, Math.max(0, props.meta.duration - 1 / FPS))
}

const playback = useHtmlPlayback({
  meta: () => props.meta,
  onSeek: (t) => {
    if (frameReady.value) post(seekMessage(pageTime(t)))
  },
})

let loadToken = 0
async function loadPage(hash: string): Promise<void> {
  const token = ++loadToken
  frameReady.value = false
  pageError.value = null
  loadedHash.value = hash
  try {
    const html = await getHtmlPreviewPage(props.projectId)
    if (token === loadToken) pageHtml.value = html
  } catch (error) {
    if (token !== loadToken) return
    pageHtml.value = null
    pageError.value = `预览页加载失败：${error instanceof Error ? error.message : String(error)}`
  }
}

watch(
  () => props.meta.hash,
  (hash) => {
    if (shouldReloadPreview(loadedHash.value, hash)) void loadPage(hash)
  },
  { immediate: true },
)

function onMessage(event: MessageEvent): void {
  const message = parsePreviewMessage(event, frame.value?.contentWindow)
  if (message === null) return
  if (message.type === 'ready') {
    frameReady.value = true
    pageError.value = null
    post(seekMessage(pageTime(playback.t.value)))
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
        v-if="pageHtml !== null"
        ref="frame"
        :srcdoc="pageHtml"
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
      <Button
        v-if="meta.music"
        size="sm"
        :variant="playback.muted.value ? 'default' : 'outline'"
        :aria-pressed="playback.muted.value"
        aria-label="配乐静音"
        data-testid="preview-mute"
        @click="playback.setMuted(!playback.muted.value)"
      >
        <VolumeX v-if="playback.muted.value" />
        <Volume2 v-else />
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

    <p
      v-if="scoreMissing"
      class="text-muted-foreground rounded border px-3 py-2 text-xs"
      role="status"
      data-testid="preview-score-missing"
    >
      配乐还没渲染，或与当前文件对不上（旁白变了、音频被换过），预览没有声音。重新渲染配乐后会自动刷新。
    </p>

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
