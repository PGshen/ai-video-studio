import { describe, expect, it } from 'vitest'
import type { HtmlPreviewSection } from '@/types/api'
import {
  advanceClock,
  globalTime,
  hasAudio,
  loopedTime,
  musicClockTime,
  needsRealign,
  nextSection,
  playbackMode,
  sectionAt,
  sectionTicks,
  shouldReloadPreview,
  fromScoreTime,
  toScoreTime,
} from './previewClock'

const sections: HtmlPreviewSection[] = [
  { id: 'a', label: 'A', start: 0, end: 2, beats: [] },
  { id: 'b', label: 'B', start: 2, end: 5, beats: [] },
  { id: 'c', label: 'C', start: 5, end: 6, beats: [] },
]

describe('sectionAt', () => {
  it.each([
    [0, 0],
    [1.99, 0],
    [2, 1],
    [4.5, 1],
    [5, 2],
    [5.99, 2],
  ])('maps t=%f to section %i', (t, index) => {
    expect(sectionAt(sections, t)).toBe(index)
  })

  it('clamps out-of-range times and handles an empty list', () => {
    expect(sectionAt(sections, -3)).toBe(0)
    expect(sectionAt(sections, 99)).toBe(2)
    expect(sectionAt([], 1)).toBe(-1)
  })
})

describe('globalTime', () => {
  it('adds the section start to the audio time and clamps to the section', () => {
    expect(globalTime(sections[1]!, 1)).toBe(3)
    expect(globalTime(sections[1]!, -0.5)).toBe(2)
    expect(globalTime(sections[1]!, 99)).toBe(5)
  })
})

describe('advanceClock', () => {
  it('moves by wall-clock seconds and stops at the end', () => {
    expect(advanceClock(1, 0.5, 6)).toEqual({ t: 1.5, ended: false })
    expect(advanceClock(5.9, 0.5, 6)).toEqual({ t: 6, ended: true })
  })
})

describe('loopedTime', () => {
  it('jumps back to the section start when looping past its end', () => {
    expect(loopedTime(sections[1]!, 5, true)).toBe(2)
    expect(loopedTime(sections[1]!, 4.9, true)).toBe(4.9)
  })
  it('does nothing when not looping', () => {
    expect(loopedTime(sections[1]!, 5.2, false)).toBe(5.2)
  })
})

describe('nextSection', () => {
  it('returns the following section or null after the last', () => {
    expect(nextSection(sections, 0)?.id).toBe('b')
    expect(nextSection(sections, 2)).toBeNull()
  })
})

describe('sectionTicks', () => {
  it('gives each boundary between sections as a percentage of the duration', () => {
    expect(sectionTicks(sections, 6)).toEqual([(2 / 6) * 100, (5 / 6) * 100])
  })
  it('has no ticks for a single section or a zero duration', () => {
    expect(sectionTicks([sections[0]!], 2)).toEqual([])
    expect(sectionTicks(sections, 0)).toEqual([])
  })
})

describe('hasAudio', () => {
  it('looks the section up in the audio list', () => {
    const audio = [{ section_id: 'a', url: '/x' }]
    expect(hasAudio(audio, 'a')).toBe(true)
    expect(hasAudio(audio, 'b')).toBe(false)
  })
})

describe('shouldReloadPreview', () => {
  it('reloads only when the hash really changed', () => {
    expect(shouldReloadPreview(null, 'h1')).toBe(true)
    expect(shouldReloadPreview('h1', 'h1')).toBe(false)
    expect(shouldReloadPreview('h1', 'h2')).toBe(true)
    expect(shouldReloadPreview('h1', undefined)).toBe(false)
  })
})

describe('playbackMode', () => {
  const base = { hash: 'h', duration: 6, sections, audio: [], music: null }
  const music = { url: '/m.wav', gain: 1 }

  it('uses the score as the clock when there is no narration', () => {
    expect(playbackMode({ ...base, music })).toBe('music')
  })

  it('keeps the narration as the clock and lets the score follow it', () => {
    const audio = [{ section_id: 'a', url: '/a.mp3' }]
    expect(playbackMode({ ...base, audio, music })).toBe('narration')
    expect(playbackMode({ ...base, audio })).toBe('narration')
  })

  it('falls back to the wall clock with neither', () => {
    expect(playbackMode(base)).toBe('wall')
  })
})

describe('musicClockTime', () => {
  it('is the audio time clamped to the piece', () => {
    expect(musicClockTime(2.5, 6)).toBe(2.5)
    expect(musicClockTime(-1, 6)).toBe(0)
    expect(musicClockTime(99, 6)).toBe(6)
    expect(musicClockTime(Number.NaN, 6)).toBe(0)
  })
})

describe('needsRealign', () => {
  it('only moves the score when it drifted past the threshold', () => {
    expect(needsRealign(2.0, 2.2)).toBe(false)
    expect(needsRealign(2.0, 2.31)).toBe(true)
    expect(needsRealign(5.0, 2.0)).toBe(true)
    expect(needsRealign(2.0, 2.2, 0.1)).toBe(true)
  })
})

describe('toScoreTime / fromScoreTime', () => {
  it('音频时间 = 预览时间 + offset，往返互逆', () => {
    const music = { offset: 4.5 }
    expect(toScoreTime(0, music)).toBe(4.5)
    expect(toScoreTime(1.5, music)).toBe(6)
    expect(fromScoreTime(6, music)).toBe(1.5)
    expect(fromScoreTime(toScoreTime(3.25, music), music)).toBe(3.25)
  })

  it('offset 缺省、为 0 或没有配乐时恒等', () => {
    for (const music of [{ offset: 0 }, {}, null, undefined]) {
      expect(toScoreTime(2.5, music)).toBe(2.5)
      expect(fromScoreTime(2.5, music)).toBe(2.5)
    }
  })

  it('音频还没走到 offset 时预览时间为负，由 musicClockTime 夹到 0', () => {
    expect(musicClockTime(fromScoreTime(1, { offset: 4.5 }), 6)).toBe(0)
  })
})
