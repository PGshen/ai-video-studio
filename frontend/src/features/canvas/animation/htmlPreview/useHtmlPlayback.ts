/**
 * 实时预览的播放控制（设计 §7.2）：一个全局时间 `t`，由当前镜头的配音驱动。
 *
 * - 当前镜头有配音：`t = 镜头起点 + audio.currentTime`；音频播完（或走到镜头末尾）切到下一镜头。
 * - 镜头没有配音，或浏览器拒绝自动播放：回退为墙钟计时。
 * - 循环：当前镜头走到末尾就回到它的起点（音频也回到 0）。
 * - 每次 `t` 变化都通过 `onSeek` 通知预览页重画；`t` 的换算全是 `previewClock` 里的纯函数。
 * - 配乐（设计 §9.2）：短片没有旁白，配乐的 `currentTime` 就是时钟；讲解里旁白仍是时钟，配乐用另一个
 *   `Audio` 低音量跟随，偏差超过阈值才重设位置；浏览器拒绝播配乐时，短片回退墙钟，讲解继续放旁白。
 * 预览与成片的音画对齐允许有小偏差，以成片为准。
 */
import { getCurrentScope, onScopeDispose, ref } from 'vue'
import type { HtmlPreviewMeta } from '@/types/api'
import {
  advanceClock,
  globalTime,
  loopedTime,
  fromScoreTime,
  musicClockTime,
  needsRealign,
  nextSection,
  playbackMode,
  sectionAt,
  toScoreTime,
} from './previewClock'

export interface PlaybackAudio {
  src: string
  currentTime: number
  readonly paused: boolean
  /** 配乐的音量（线性增益）；旁白不调。 */
  volume?: number
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
  /** 配乐用的第二个播放器；不给就用 `createAudio`。 */
  createScoreAudio?: () => PlaybackAudio
  requestFrame?: (callback: (nowMs: number) => void) => number
  cancelFrame?: (id: number) => void
}

export function useHtmlPlayback(options: PlaybackOptions) {
  const t = ref(0)
  const playing = ref(false)
  const loop = ref(false)
  const currentIndex = ref(0)
  const muted = ref(false)

  const requestFrame = options.requestFrame ?? ((cb) => requestAnimationFrame(cb))
  const cancelFrame = options.cancelFrame ?? ((id) => cancelAnimationFrame(id))
  let audio: PlaybackAudio | null = null
  let audioDriven = false
  let score: PlaybackAudio | null = null
  let scoreUrl: string | null = null
  /** 短片：配乐的 `currentTime` 是时钟。 */
  let scoreDriven = false
  let frameId: number | null = null
  let startToken = 0
  let lastMs: number | null = null

  function ensureAudio(): PlaybackAudio {
    if (audio === null) {
      audio = options.createAudio ? options.createAudio() : new Audio()
      audio.addEventListener('ended', onAudioEnded)
    }
    return audio
  }

  function ensureScore(): PlaybackAudio {
    if (score === null) {
      const create = options.createScoreAudio ?? options.createAudio
      score = create ? create() : new Audio()
    }
    return score
  }

  function applyVolume(gain: number): void {
    if (score !== null) score.volume = muted.value ? 0 : gain
  }

  function pauseScore(): void {
    score?.pause()
  }

  /** 配乐是时钟时要贴得很近；只是跟随旁白时允许 `REALIGN` 的偏差。 */
  const CLOCK_TOLERANCE_SECONDS = 0.05

  function startScore(meta: HtmlPreviewMeta, at: number, clock: boolean, token: number): void {
    const music = meta.music
    if (music === null) {
      pauseScore()
      return
    }
    const el = ensureScore()
    if (scoreUrl !== music.url) {
      el.src = music.url
      scoreUrl = music.url
    }
    applyVolume(music.gain)
    const playedAt = fromScoreTime(el.currentTime, music)
    const off = clock
      ? Math.abs(playedAt - at) > CLOCK_TOLERANCE_SECONDS
      : needsRealign(playedAt, at)
    if (off) el.currentTime = toScoreTime(at, music)
    el.play().catch((error: unknown) => {
      const aborted = error instanceof DOMException && error.name === 'AbortError'
      // 短片：配乐放不了就回退墙钟；讲解：背景乐放不了不影响旁白。
      if (clock && token === startToken && !aborted) scoreDriven = false
    })
  }

  /** 每帧：配乐的地址变了（重新渲染）就换源并接着放；配乐没了就停；跟随旁白时纠正漂移。 */
  function syncScore(meta: HtmlPreviewMeta, shown: number): void {
    if (score === null) return
    const music = meta.music
    if (music === null) {
      if (!score.paused) score.pause()
      scoreUrl = null
      scoreDriven = false
      return
    }
    if (scoreUrl !== music.url) {
      const resume = !score.paused
      score.src = music.url
      scoreUrl = music.url
      score.currentTime = toScoreTime(shown, music)
      applyVolume(music.gain)
      if (resume) void score.play().catch(() => undefined)
      return
    }
    if (!scoreDriven && !score.paused && needsRealign(fromScoreTime(score.currentTime, music), shown)) {
      score.currentTime = toScoreTime(shown, music)
    }
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
    const token = ++startToken
    const at = section.start + localSeconds
    if (playbackMode(meta) === 'music') {
      audio?.pause()
      audioDriven = false
      scoreDriven = true
      startScore(meta, at, true, token)
      return
    }
    scoreDriven = false
    startScore(meta, at, false, token)
    audioDriven = clip !== undefined
    if (clip === undefined) {
      audio?.pause()
      return
    }
    const el = ensureAudio()
    if (!el.src.endsWith(clip.url) && el.src !== clip.url) el.src = clip.url
    el.currentTime = localSeconds
    el.play().catch((error: unknown) => {
      // 换了 src / 重新定位会让上一次还没完成的 play() 以 AbortError 被拒绝，那不代表当前这段
      // 播不了：只有最新一次启动、且不是被打断的拒绝，才回退墙钟（不卡在"播放中但没动静"）。
      const aborted = error instanceof DOMException && error.name === 'AbortError'
      if (token === startToken && !aborted) audioDriven = false
    })
  }

  function finish(): void {
    const meta = options.meta()
    playing.value = false
    audio?.pause()
    pauseScore()
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
    if (meta === undefined || section === undefined) {
      finish() // 镜头被改少了，当前镜头已不存在：停下，不要假装在播
      return
    }
    const delta = lastMs === null ? 0 : (nowMs - lastMs) / 1000
    lastMs = nowMs

    let next: number
    if (scoreDriven && score !== null && !score.paused) {
      next = musicClockTime(fromScoreTime(score.currentTime, meta.music), meta.duration)
    } else if (audioDriven && audio !== null && !audio.paused) {
      next = globalTime(section, audio.currentTime)
    } else {
      next = advanceClock(t.value, delta, meta.duration).t
    }
    syncScore(meta, next)
    if (loopedTime(section, next, loop.value) !== next) {
      show(section.start) // looping: back to the section start, audio included
      startSection(currentIndex.value, 0)
    } else if (next >= section.end) {
      if (scoreDriven && score !== null && !score.paused) {
        // The score is the clock and keeps playing: only follow it. Seeking it to the next
        // section start would pull it back after a late frame or a background tab.
        if (next >= meta.duration) finish()
        else {
          currentIndex.value = Math.max(0, sectionAt(meta.sections, next))
          show(next)
        }
      } else {
        advanceSection()
      }
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
      pauseScore()
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

  /** 静音只管配乐，旁白不受影响。 */
  function setMuted(value: boolean): void {
    muted.value = value
    applyVolume(options.meta()?.music?.gain ?? 1)
  }

  function dispose(): void {
    playing.value = false
    audio?.pause()
    pauseScore()
    audio?.removeEventListener('ended', onAudioEnded)
    cancelLoop()
  }
  if (getCurrentScope()) onScopeDispose(dispose)

  return {
    t,
    playing,
    loop,
    muted,
    currentIndex,
    toggle,
    seekTo,
    jumpToSection,
    setLoop,
    setMuted,
    dispose,
  }
}
