import { describe, expect, it } from 'vitest'
import {
  eventMarkers,
  sectionBands,
  timeToX,
  waveformPeaks,
  xToTime,
} from './waveform'

describe('timeToX / xToTime', () => {
  it('maps time linearly onto the width and back', () => {
    expect(timeToX(5, 10, 200)).toBe(100)
    expect(xToTime(100, 10, 200)).toBe(5)
    expect(xToTime(timeToX(3.3, 12, 480), 12, 480)).toBeCloseTo(3.3, 9)
  })

  it.each([
    ['zero duration', 3, 0, 200],
    ['zero width', 3, 10, 0],
    ['negative duration', 3, -4, 200],
  ])('is 0 for %s', (_name, t, duration, width) => {
    expect(timeToX(t, duration, width)).toBe(0)
    expect(xToTime(t, duration, width)).toBe(0)
  })

  it('clamps times and positions outside the range', () => {
    expect(timeToX(-2, 10, 200)).toBe(0)
    expect(timeToX(99, 10, 200)).toBe(200)
    expect(xToTime(-5, 10, 200)).toBe(0)
    expect(xToTime(999, 10, 200)).toBe(10)
  })

  it('treats non-finite input as 0', () => {
    expect(timeToX(Number.NaN, 10, 200)).toBe(0)
    expect(xToTime(Number.NaN, 10, 200)).toBe(0)
  })
})

describe('waveformPeaks', () => {
  it('gives one symmetric bar per point around the vertical middle', () => {
    const bars = waveformPeaks([0, 0.5, 1], 300, 100)
    expect(bars).toHaveLength(3)
    expect(bars[0]).toEqual({ x: 0, width: 100, top: 50, bottom: 50 })
    expect(bars[1]).toEqual({ x: 100, width: 100, top: 25, bottom: 75 })
    expect(bars[2]).toEqual({ x: 200, width: 100, top: 0, bottom: 100 })
  })

  it('clamps out-of-range amplitudes and survives empty input and zero sizes', () => {
    expect(waveformPeaks([2, -1], 20, 10)).toEqual([
      { x: 0, width: 10, top: 0, bottom: 10 },
      { x: 10, width: 10, top: 5, bottom: 5 },
    ])
    expect(waveformPeaks([], 300, 100)).toEqual([])
    expect(waveformPeaks([0.5], 0, 100)).toEqual([])
    expect(waveformPeaks([0.5], 300, 0)).toEqual([])
  })

  it('treats NaN as silence', () => {
    expect(waveformPeaks([Number.NaN], 10, 10)).toEqual([{ x: 0, width: 10, top: 5, bottom: 5 }])
  })
})

describe('eventMarkers', () => {
  const events = [
    { name: 'kick', kind: 'onset', start: 0, end: 0.2 },
    { name: 'riser', kind: 'sweep', start: 2, end: 4 },
  ]

  it('puts onsets on a line and sweeps on a span', () => {
    const markers = eventMarkers(events, 10, 100)
    expect(markers[0]).toEqual({ name: 'kick', kind: 'onset', x: 0, width: 0 })
    expect(markers[1]).toEqual({ name: 'riser', kind: 'sweep', x: 20, width: 20 })
  })

  it('is empty without duration or width, and clamps events past the end', () => {
    expect(eventMarkers(events, 0, 100)).toEqual([])
    expect(eventMarkers(events, 10, 0)).toEqual([])
    const late = eventMarkers([{ name: 'x', kind: 'sweep', start: 9, end: 30 }], 10, 100)
    expect(late[0]).toEqual({ name: 'x', kind: 'sweep', x: 90, width: 10 })
  })
})

describe('sectionBands', () => {
  it('returns each section as an x range', () => {
    const bands = sectionBands(
      [
        { id: 'a', label: 'A', start: 0, end: 4 },
        { id: 'b', label: 'B', start: 4, end: 10 },
      ],
      10,
      200,
    )
    expect(bands).toEqual([
      { id: 'a', label: 'A', x: 0, width: 80 },
      { id: 'b', label: 'B', x: 80, width: 120 },
    ])
  })

  it('is empty for no duration or no sections', () => {
    expect(sectionBands([], 10, 200)).toEqual([])
    expect(sectionBands([{ id: 'a', label: 'A', start: 0, end: 1 }], 0, 200)).toEqual([])
  })
})
