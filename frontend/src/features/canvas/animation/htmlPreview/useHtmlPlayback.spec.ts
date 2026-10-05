import { effectScope } from 'vue'
import { describe, expect, it } from 'vitest'
import type { HtmlPreviewMeta } from '@/types/api'
import { useHtmlPlayback, type PlaybackAudio } from './useHtmlPlayback'

class FakeAudio implements PlaybackAudio {
  src = ''
  volume = 1
  currentTime = 0
  paused = true
  playRejects = false
  plays = 0
  /** When set, `play()` stays pending until `settle(index, 'abort')` rejects it or `'ok'` resolves it. */
  deferPlays = false
  private pendingPlays: Array<{ resolve: () => void; reject: (e: Error) => void }> = []
  private listeners: Record<string, Array<() => void>> = {}
  addEventListener(type: string, fn: () => void): void {
    ;(this.listeners[type] ??= []).push(fn)
  }
  removeEventListener(type: string, fn: () => void): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn)
  }
  play(): Promise<void> {
    this.plays += 1
    if (this.deferPlays) {
      this.paused = false
      return new Promise<void>((resolve, reject) => this.pendingPlays.push({ resolve, reject }))
    }
    if (this.playRejects) return Promise.reject(new Error('NotAllowedError'))
    this.paused = false
    return Promise.resolve()
  }
  pause(): void {
    this.paused = true
  }
  settle(index: number, how: 'ok' | 'abort'): void {
    const play = this.pendingPlays[index]
    if (how === 'ok') play?.resolve()
    else play?.reject(new DOMException('interrupted by a new load', 'AbortError'))
  }
  emit(type: string): void {
    for (const fn of this.listeners[type] ?? []) fn()
  }
}

const META: HtmlPreviewMeta = {
  hash: 'h',
  duration: 6,
  sections: [
    { id: 'a', label: 'A', start: 0, end: 2, beats: [] },
    { id: 'b', label: 'B', start: 2, end: 5, beats: [] },
    { id: 'c', label: 'C', start: 5, end: 6, beats: [] },
  ],
  audio: [
    { section_id: 'a', url: '/audio/a.wav' },
    { section_id: 'c', url: '/audio/c.wav' },
  ],
  music: null,
}

function setup(meta: HtmlPreviewMeta | null = META) {
  const audio = new FakeAudio()
  const seeks: number[] = []
  let frame: ((ms: number) => void) | null = null
  let now = 0
  const scope = effectScope()
  const playback = scope.run(() =>
    useHtmlPlayback({
      meta: () => meta ?? undefined,
      onSeek: (t) => seeks.push(t),
      createAudio: () => audio,
      requestFrame: (cb) => {
        frame = cb
        return 1
      },
      cancelFrame: () => {
        frame = null
      },
    }),
  )!
  /** Advance the wall clock by `seconds` and run one animation frame. */
  const tick = (seconds: number): void => {
    now += seconds * 1000
    const cb = frame
    frame = null
    cb?.(now)
  }
  const scheduled = (): boolean => frame !== null
  return { playback, audio, seeks, tick, scheduled, scope }
}

async function started(h: ReturnType<typeof setup>): Promise<void> {
  h.playback.toggle()
  await Promise.resolve()
  h.tick(0) // first frame only records the wall-clock origin
}

describe('useHtmlPlayback', () => {
  it('plays the first section from its audio and follows audio.currentTime', async () => {
    const h = setup()
    await started(h)
    expect(h.playback.playing.value).toBe(true)
    expect(h.audio.src).toContain('/audio/a.wav')
    h.audio.currentTime = 1
    h.tick(0.016)
    expect(h.playback.t.value).toBe(1)
    expect(h.seeks.at(-1)).toBe(1)
  })

  it('falls back to wall-clock time for a section without audio', async () => {
    const h = setup()
    h.playback.seekTo(2.5) // section b has no audio
    h.playback.toggle()
    await Promise.resolve()
    h.tick(0)
    h.tick(0.5)
    expect(h.playback.t.value).toBeCloseTo(3.0)
    expect(h.audio.plays).toBe(0)
  })

  it('moves to the next section when audio ends and loads its audio', async () => {
    const h = setup()
    await started(h)
    h.audio.emit('ended')
    expect(h.playback.t.value).toBe(2) // section b starts at 2 (no audio: wall clock)
    h.audio.currentTime = 0
    h.playback.seekTo(5)
    expect(h.audio.src).toContain('/audio/c.wav')
  })

  it('stops at the very end and rewinds on the next play', async () => {
    const h = setup()
    h.playback.seekTo(5.2)
    h.playback.toggle()
    await Promise.resolve()
    h.audio.emit('ended')
    expect(h.playback.playing.value).toBe(false)
    expect(h.playback.t.value).toBe(6)
    expect(h.scheduled()).toBe(false)
    h.playback.toggle()
    await Promise.resolve()
    expect(h.playback.t.value).toBe(0)
    expect(h.playback.playing.value).toBe(true)
  })

  it('loops the current section: past its end it goes back to the start and restarts audio', async () => {
    const h = setup()
    h.playback.setLoop(true)
    await started(h)
    h.audio.currentTime = 2
    h.tick(0.016) // audio is at the section end
    expect(h.playback.t.value).toBe(0)
    expect(h.audio.currentTime).toBe(0)
    expect(h.playback.playing.value).toBe(true)
  })

  it('seeking while paused only updates the time and the page', () => {
    const h = setup()
    h.playback.seekTo(3)
    expect(h.playback.t.value).toBe(3)
    expect(h.playback.currentIndex.value).toBe(1)
    expect(h.seeks).toEqual([3])
    expect(h.audio.plays).toBe(0)
  })

  it('seeking while playing restarts from the new section audio at the right offset', async () => {
    const h = setup()
    await started(h)
    h.playback.seekTo(5.5)
    await Promise.resolve()
    expect(h.audio.src).toContain('/audio/c.wav')
    expect(h.audio.currentTime).toBeCloseTo(0.5)
  })

  it('pausing stops the audio and the frame loop', async () => {
    const h = setup()
    await started(h)
    h.playback.toggle()
    expect(h.playback.playing.value).toBe(false)
    expect(h.audio.paused).toBe(true)
    expect(h.scheduled()).toBe(false)
  })

  it('keeps playing on the wall clock when the browser refuses to play audio', async () => {
    const h = setup()
    h.audio.playRejects = true
    h.playback.toggle()
    await Promise.resolve()
    await Promise.resolve()
    h.tick(0)
    h.tick(0.5)
    expect(h.playback.playing.value).toBe(true)
    expect(h.playback.t.value).toBeCloseTo(0.5)
  })

  it('ignores the rejection of an older play() after the audio was switched (fast clicking)', async () => {
    const h = setup()
    h.audio.deferPlays = true
    h.playback.toggle() // play #0 for section a, still pending
    h.playback.seekTo(5.5) // play #1 for section c replaces it
    h.audio.settle(0, 'abort') // the browser aborts the older play() because src changed
    await Promise.resolve()
    await Promise.resolve()
    h.tick(0)
    h.audio.currentTime = 0.7
    h.tick(0.016)
    expect(h.playback.t.value).toBeCloseTo(5.7) // still audio-driven, not wall-clock
  })

  it('stops instead of pretending to play when the sections shrink under it', async () => {
    let meta: HtmlPreviewMeta | null = META
    const audio = new FakeAudio()
    let frame: ((ms: number) => void) | null = null
    const scope = effectScope()
    const playback = scope.run(() =>
      useHtmlPlayback({
        meta: () => meta ?? undefined,
        onSeek: () => {},
        createAudio: () => audio,
        requestFrame: (cb) => {
          frame = cb
          return 1
        },
        cancelFrame: () => {
          frame = null
        },
      }),
    )!
    playback.seekTo(5.5)
    playback.toggle()
    await Promise.resolve()
    meta = { ...META, sections: META.sections.slice(0, 1), duration: 2 }
    ;(frame as ((ms: number) => void) | null)?.(16)
    expect(playback.playing.value).toBe(false)
    expect(audio.paused).toBe(true)
    scope.stop()
  })

  it('does nothing before the meta is available', () => {
    const h = setup(null)
    h.playback.toggle()
    expect(h.playback.playing.value).toBe(false)
    h.playback.seekTo(1)
    expect(h.seeks).toEqual([])
  })

  it('jumpToSection seeks to the section start', () => {
    const h = setup()
    h.playback.jumpToSection(2)
    expect(h.playback.t.value).toBe(5)
  })

  it('stops everything when the scope is disposed', async () => {
    const h = setup()
    await started(h)
    h.scope.stop()
    expect(h.audio.paused).toBe(true)
    expect(h.scheduled()).toBe(false)
  })
})



// ---- the score (3B T6) ------------------------------------------------------------------

const REEL: HtmlPreviewMeta = {
  hash: 'r',
  duration: 6,
  sections: META.sections,
  audio: [],
  music: { url: '/music/audio?v=one', gain: 1 },
}
const BED: HtmlPreviewMeta = { ...META, music: { url: '/music/audio?v=one', gain: 0.4 } }

function setupScore(initial: HtmlPreviewMeta) {
  const narration = new FakeAudio()
  const score = new FakeAudio()
  let meta = initial
  let created = 0
  const seeks: number[] = []
  let frame: ((ms: number) => void) | null = null
  let now = 0
  const scope = effectScope()
  const playback = scope.run(() =>
    useHtmlPlayback({
      meta: () => meta,
      onSeek: (t) => seeks.push(t),
      createAudio: () => narration,
      createScoreAudio: () => {
        created += 1
        return score
      },
      requestFrame: (cb) => {
        frame = cb
        return 1
      },
      cancelFrame: () => {
        frame = null
      },
    }),
  )!
  const tick = (seconds: number): void => {
    now += seconds * 1000
    const cb = frame
    frame = null
    cb?.(now)
  }
  return {
    playback,
    narration,
    score,
    seeks,
    tick,
    scope,
    setMeta: (next: HtmlPreviewMeta) => {
      meta = next
    },
    created: () => created,
  }
}

async function playing(h: ReturnType<typeof setupScore>): Promise<void> {
  h.playback.toggle()
  await Promise.resolve()
  h.tick(0)
}

describe('useHtmlPlayback with a score: a reel (no narration)', () => {
  it('plays the score and uses its currentTime as the clock', async () => {
    const h = setupScore(REEL)
    await playing(h)
    expect(h.score.src).toContain('/music/audio?v=one')
    expect(h.score.paused).toBe(false)
    expect(h.score.volume).toBe(1)
    h.score.currentTime = 1.5
    h.tick(0.016)
    expect(h.playback.t.value).toBe(1.5)
    expect(h.seeks.at(-1)).toBe(1.5)
    expect(h.narration.plays).toBe(0)
  })

  it('crosses into the next section without seeking the score', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.score.currentTime = 2.02
    h.tick(0.016)
    expect(h.playback.currentIndex.value).toBe(1)
    expect(h.score.currentTime).toBe(2.02) // already in place: no jump, no click
  })

  it('never pulls the score back when a frame was late or several sections went by', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.score.currentTime = 2.2 // a slow frame: well past the 2.0 boundary
    h.tick(0.016)
    expect(h.playback.currentIndex.value).toBe(1)
    expect(h.score.currentTime).toBe(2.2)
    expect(h.playback.t.value).toBe(2.2)

    h.score.currentTime = 5.4 // the tab was in the background: two sections at once
    h.tick(0.016)
    expect(h.playback.currentIndex.value).toBe(2)
    expect(h.score.currentTime).toBe(5.4)
  })

  it('stops at the end of the piece when the score reaches it', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.score.currentTime = 6
    h.tick(0.016)
    expect(h.playback.playing.value).toBe(false)
    expect(h.playback.t.value).toBe(6)
  })

  it('loops the current section by moving the score back to the section start', async () => {
    const h = setupScore(REEL)
    h.playback.setLoop(true)
    await playing(h)
    h.score.currentTime = 2.05
    h.tick(0.016)
    expect(h.score.currentTime).toBe(0)
    expect(h.playback.t.value).toBe(0)
  })

  it('seeking while playing moves the score to the global time', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.playback.seekTo(3.2)
    expect(h.score.currentTime).toBe(3.2)
  })

  it('seeking while paused only moves the page', () => {
    const h = setupScore(REEL)
    h.playback.seekTo(3.2)
    expect(h.score.plays).toBe(0)
    expect(h.playback.t.value).toBe(3.2)
  })

  it('keeps going on the wall clock when the browser refuses to play the score', async () => {
    const h = setupScore(REEL)
    h.score.playRejects = true
    await playing(h)
    await Promise.resolve()
    h.tick(0.5)
    expect(h.playback.t.value).toBeCloseTo(0.5, 5)
    expect(h.playback.playing.value).toBe(true)
  })

  it('pausing pauses the score and ends at the end of the piece', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.playback.toggle()
    expect(h.score.paused).toBe(true)
    expect(h.playback.playing.value).toBe(false)
  })

  it('reloads the score when a new render changed its address, keeping the position', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.score.currentTime = 1.2
    h.tick(0.016)
    h.setMeta({ ...REEL, music: { url: '/music/audio?v=two', gain: 1 } })
    h.tick(0.016)
    expect(h.score.src).toContain('v=two')
    expect(h.score.currentTime).toBeCloseTo(1.2, 5)
    expect(h.score.paused).toBe(false)
  })

  it('stops the score when the render goes away', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.setMeta({ ...REEL, music: null })
    h.tick(0.016)
    expect(h.score.paused).toBe(true)
  })

  it('muting silences only the score and unmuting restores the gain', async () => {
    const h = setupScore({ ...REEL, music: { url: '/m', gain: 0.5 } })
    await playing(h)
    expect(h.score.volume).toBe(0.5)
    h.playback.setMuted(true)
    expect(h.score.volume).toBe(0)
    h.playback.setMuted(false)
    expect(h.score.volume).toBe(0.5)
  })

  it('is stopped for good when the scope is disposed', async () => {
    const h = setupScore(REEL)
    await playing(h)
    h.scope.stop()
    expect(h.score.paused).toBe(true)
  })
})

describe('useHtmlPlayback with a score: narration plus a bed', () => {
  it('keeps the narration as the clock and starts the bed at the global time, quieter', async () => {
    const h = setupScore(BED)
    await playing(h)
    expect(h.narration.src).toContain('/audio/a.wav')
    expect(h.score.src).toContain('/music/audio?v=one')
    expect(h.score.volume).toBe(0.4)
    h.narration.currentTime = 1
    h.score.currentTime = 1.05
    h.tick(0.016)
    expect(h.playback.t.value).toBe(1) // narration is the clock
    expect(h.score.currentTime).toBe(1.05) // within the drift allowance: untouched
  })

  it('pulls the bed back only when it drifted past the threshold', async () => {
    const h = setupScore(BED)
    await playing(h)
    h.narration.currentTime = 1
    h.score.currentTime = 1.5
    h.tick(0.016)
    expect(h.score.currentTime).toBe(1)
  })

  it('aligns the bed on seeks and section changes', async () => {
    const h = setupScore(BED)
    await playing(h)
    h.playback.seekTo(5.4)
    expect(h.score.currentTime).toBeCloseTo(5.4, 5)
  })

  it('keeps the bed running through a section without narration on the wall clock', async () => {
    const h = setupScore(BED)
    h.playback.seekTo(2.5)
    h.playback.toggle()
    await Promise.resolve()
    h.tick(0)
    h.tick(0.5)
    expect(h.playback.t.value).toBeCloseTo(3.0, 5)
    expect(h.score.paused).toBe(false)
  })

  it('does not stop the narration when the browser refuses the bed', async () => {
    const h = setupScore(BED)
    h.score.playRejects = true
    await playing(h)
    await Promise.resolve()
    h.narration.currentTime = 0.5
    h.tick(0.016)
    expect(h.playback.t.value).toBe(0.5)
    expect(h.playback.playing.value).toBe(true)
  })

  it('pauses the bed together with the narration', async () => {
    const h = setupScore(BED)
    await playing(h)
    h.playback.toggle()
    expect(h.narration.paused).toBe(true)
    expect(h.score.paused).toBe(true)
  })
})

describe('useHtmlPlayback without a score', () => {
  it('never creates a score audio element', async () => {
    const h = setupScore({ ...META, music: null })
    await playing(h)
    expect(h.created()).toBe(0)
  })
})

// ---- an imported song: audio time = preview time + music.offset (4B T8) ----------------------

const OFFSET = 4.5
const MV: HtmlPreviewMeta = {
  ...REEL,
  music: { url: '/music/audio?v=song', gain: 1, offset: OFFSET },
}

describe('useHtmlPlayback with an offset score', () => {
  it('starts the song at offset + the preview time', async () => {
    const h = setupScore(MV)
    await playing(h)
    expect(h.score.currentTime).toBe(OFFSET)
    expect(h.score.paused).toBe(false)
  })

  it('takes the clock from the song minus the offset', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.score.currentTime = OFFSET + 1.5
    h.tick(0.016)
    expect(h.playback.t.value).toBe(1.5)
    expect(h.seeks.at(-1)).toBe(1.5)
  })

  it('crosses sections without seeking the song', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.score.currentTime = OFFSET + 2.2
    h.tick(0.016)
    expect(h.playback.currentIndex.value).toBe(1)
    expect(h.score.currentTime).toBe(OFFSET + 2.2)
    expect(h.playback.t.value).toBe(2.2)
  })

  it('stops at the end of the piece when the song reaches offset + duration', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.score.currentTime = OFFSET + 6
    h.tick(0.016)
    expect(h.playback.playing.value).toBe(false)
    expect(h.playback.t.value).toBe(6)
    h.score.currentTime = OFFSET + 99 // past the cut: still clamped to the piece
    expect(h.playback.t.value).toBe(6)
  })

  it('seeking while playing moves the song to offset + the global time', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.playback.seekTo(3.2)
    expect(h.score.currentTime).toBe(OFFSET + 3.2)
  })

  it('resuming after a pause continues from offset + t', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.score.currentTime = OFFSET + 1
    h.tick(0.016)
    h.playback.toggle() // pause
    h.score.currentTime = 0 // the browser may have moved it meanwhile
    h.playback.toggle() // resume
    await Promise.resolve()
    expect(h.score.currentTime).toBe(OFFSET + 1)
  })

  it('loops the section by moving the song back to offset + the section start', async () => {
    const h = setupScore(MV)
    h.playback.setLoop(true)
    await playing(h)
    h.score.currentTime = OFFSET + 2.05
    h.tick(0.016)
    expect(h.score.currentTime).toBe(OFFSET)
    expect(h.playback.t.value).toBe(0)
  })

  it('keeps the position when a changed song address reloads the source', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.score.currentTime = OFFSET + 1.2
    h.tick(0.016)
    h.setMeta({ ...MV, music: { url: '/music/audio?v=other', gain: 1, offset: OFFSET } })
    h.tick(0.016)
    expect(h.score.src).toContain('v=other')
    expect(h.score.currentTime).toBeCloseTo(OFFSET + 1.2, 5)
    expect(h.score.paused).toBe(false)
  })

  it('with narration the song only follows: drift is measured against offset + t', async () => {
    const h = setupScore({ ...BED, music: { url: '/m', gain: 0.4, offset: OFFSET } })
    await playing(h)
    h.narration.currentTime = 1
    h.score.currentTime = OFFSET + 1.05 // within the allowance
    h.tick(0.016)
    expect(h.score.currentTime).toBe(OFFSET + 1.05)
    h.score.currentTime = OFFSET + 3 // far off
    h.tick(0.016)
    expect(h.score.currentTime).toBeCloseTo(OFFSET + 1, 1)
  })

  it('offset 0 or missing behaves exactly like before', async () => {
    const h = setupScore({ ...REEL, music: { url: '/m', gain: 1, offset: 0 } })
    await playing(h)
    h.score.currentTime = 1.5
    h.tick(0.016)
    expect(h.playback.t.value).toBe(1.5)
  })

  it('a new meta that changes the song and the offset at once does not make the picture jump', async () => {
    const h = setupScore(MV)
    await playing(h)
    h.score.currentTime = OFFSET + 1.2
    h.tick(0.016)
    expect(h.playback.t.value).toBeCloseTo(1.2, 5)
    h.setMeta({ ...MV, music: { url: '/music/audio?v=other', gain: 1, offset: 9 } })
    h.score.currentTime = OFFSET + 1.3 // still the old element position, old mapping
    h.tick(0.016)
    expect(h.playback.t.value).toBeCloseTo(1.3, 5) // not 1.3 + 4.5 - 9
    expect(h.score.src).toContain('v=other')
    expect(h.score.currentTime).toBeCloseTo(9 + 1.3, 5) // new song at the new mapping
  })
})
