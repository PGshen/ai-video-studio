/**
 * 实时预览的播放控制（设计 §7.2）：一个全局时间 `t`，由当前镜头的配音驱动。
 *
 * - 当前镜头有配音：`t = 镜头起点 + audio.currentTime`；音频播完（或走到镜头末尾）切到下一镜头。
 * - 镜头没有配音，或浏览器拒绝自动播放：回退为墙钟计时。
 * - 循环：当前镜头走到末尾就回到它的起点（音频也回到 0）。
 * - 每次 `t` 变化都通过 `onSeek` 通知预览页重画；`t` 的换算全是 `previewClock` 里的纯函数。
 * 预览与成片的音画对齐允许有小偏差，以成片为准。
 */
import { getCurrentScope, onScopeDispose, ref } from 'vue'
import type { HtmlPreviewMeta } from '@/types/api'
import { advanceClock, globalTime, loopedTime, nextSection, sectionAt } from './previewClock'

export interface PlaybackAudio {
  src: string
  currentTime: number
  readonly paused: boolean
  play(): Promise<void>
  pause(): void
  addEventListener(type: string, listener: () => void): void
  removeEventListener(type: string, listener: () => void): void
}

export interface PlaybackOptions {
  meta: () => HtmlPreviewMeta | undefined
  /** 显示的时间变了（播放、跳转、循环）：把它转给预览页。 */
  onSeek: (t: number) => void
  createAudio?: () => PlaybackAudio
  requestFrame?: (callback: (nowMs: number) => void) => number
  cancelFrame?: (id: number) => void
}

export function useHtmlPlayback(options: PlaybackOptions) {
  const t = ref(0)
  const playing = ref(false)
  const loop = ref(false)
  const currentIndex = ref(0)

  const requestFrame = options.requestFrame ?? ((cb) => requestAnimationFrame(cb))
  const cancelFrame = options.cancelFrame ?? ((id) => cancelAnimationFrame(id))
  let audio: PlaybackAudio | null = null
  let audioDriven = false
  let frameId: number | null = null
  let lastMs: number | null = null

  function ensureAudio(): PlaybackAudio {
    if (audio === null) {
      audio = options.createAudio ? options.createAudio() : new Audio()
      audio.addEventListener('ended', onAudioEnded)
    }
    return audio
  }

  function show(time: number): void {
    t.value = time
    options.onSeek(time)
  }

  /** 从镜头 `index` 的 `localSeconds` 处开始驱动：有配音就播，没有（或被拒）就用墙钟。 */
  function startSection(index: number, localSeconds: number): void {
    const meta = options.meta()
    const section = meta?.sections[index]
    if (meta === undefined || section === undefined) return
    currentIndex.value = index
    const clip = meta.audio.find((item) => item.section_id === section.id)
    audioDriven = clip !== undefined
    if (clip === undefined) {
      audio?.pause()
      return
    }
    const el = ensureAudio()
    if (!el.src.endsWith(clip.url) && el.src !== clip.url) el.src = clip.url
    el.currentTime = localSeconds
    el.play().catch(() => {
      audioDriven = false // 浏览器拒绝播放：回退墙钟，不卡在"播放中但没动静"
    })
  }

  function finish(): void {
    const meta = options.meta()
    playing.value = false
    audio?.pause()
    cancelLoop()
    if (meta !== undefined) show(meta.duration)
  }

  /** 当前镜头播完：循环则回到镜头起点，否则进入下一个镜头，最后一个镜头之后结束。 */
  function advanceSection(): void {
    const meta = options.meta()
    if (meta === undefined) return
    const index = currentIndex.value
    const section = meta.sections[index]
    if (section === undefined) return
    if (loop.value) {
      show(section.start)
      startSection(index, 0)
      return
    }
    const next = nextSection(meta.sections, index)
    if (next === null) {
      finish()
      return
    }
    show(next.start)
    startSection(index + 1, 0)
  }

  function onAudioEnded(): void {
    if (playing.value && audioDriven) advanceSection()
  }

  function onFrame(nowMs: number): void {
    frameId = null
    if (!playing.value) return
    const meta = options.meta()
    const section = meta?.sections[currentIndex.value]
    if (meta === undefined || section === undefined) return
    const delta = lastMs === null ? 0 : (nowMs - lastMs) / 1000
    lastMs = nowMs

    let next: number
    if (audioDriven && audio !== null && !audio.paused) {
      next = globalTime(section, audio.currentTime)
    } else {
      next = advanceClock(t.value, delta, meta.duration).t
    }
    if (loopedTime(section, next, loop.value) !== next) {
      show(section.start) // looping: back to the section start, audio included
      startSection(currentIndex.value, 0)
    } else if (next >= section.end) {
      advanceSection()
    } else if (next !== t.value) {
      show(next)
    }
    if (playing.value) frameId = requestFrame(onFrame)
  }

  function cancelLoop(): void {
    if (frameId !== null) cancelFrame(frameId)
    frameId = null
    lastMs = null
  }

  function toggle(): void {
    const meta = options.meta()
    if (meta === undefined) return
    if (playing.value) {
      playing.value = false
      audio?.pause()
      cancelLoop()
      return
    }
    if (t.value >= meta.duration) show(0)
    const index = Math.max(0, sectionAt(meta.sections, t.value))
    const section = meta.sections[index]
    if (section === undefined) return
    playing.value = true
    startSection(index, t.value - section.start)
    cancelLoop()
    frameId = requestFrame(onFrame)
  }

  function seekTo(time: number): void {
    const meta = options.meta()
    if (meta === undefined) return
    const clamped = Math.min(meta.duration, Math.max(0, time))
    const index = Math.max(0, sectionAt(meta.sections, clamped))
    currentIndex.value = index
    show(clamped)
    const section = meta.sections[index]
    if (playing.value && section !== undefined) {
      startSection(index, clamped - section.start)
      lastMs = null
    }
  }

  function jumpToSection(index: number): void {
    const section = options.meta()?.sections[index]
    if (section !== undefined) seekTo(section.start)
  }

  function setLoop(value: boolean): void {
    loop.value = value
  }

  function dispose(): void {
    playing.value = false
    audio?.pause()
    audio?.removeEventListener('ended', onAudioEnded)
    cancelLoop()
  }
  if (getCurrentScope()) onScopeDispose(dispose)

  return { t, playing, loop, currentIndex, toggle, seekTo, jumpToSection, setLoop, dispose }
}
