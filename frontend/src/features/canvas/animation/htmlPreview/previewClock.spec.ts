import { describe, expect, it } from 'vitest'
import type { HtmlPreviewSection } from '@/types/api'
import {
  advanceClock,
  globalTime,
  hasAudio,
  loopedTime,
  nextSection,
  sectionAt,
  sectionTicks,
  shouldReloadPreview,
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
