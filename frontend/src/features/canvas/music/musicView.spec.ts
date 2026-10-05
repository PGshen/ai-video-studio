import { describe, expect, it } from 'vitest'
import { formatClock, matchRows, metricRows, metricWarnings } from './musicView'

describe('formatClock', () => {
  it.each([
    [0, '0:00.0'],
    [11.25, '0:11.3'],
    [75.04, '1:15.0'],
    [-3, '0:00.0'],
    [Number.NaN, '0:00.0'],
  ])('formats %f as %s', (seconds, text) => {
    expect(formatClock(seconds)).toBe(text)
  })
})

const METRICS = {
  peak_dbfs: -1.04,
  clipped_samples: 0,
  rms_dbfs: -12.2,
  grid_alignment: 0.873,
  onsets: 56,
  warnings: ['整体 RMS 偏高', '另一条'],
  event_matches: [
    { name: 'kick', detectable: 10, matched: 9 },
    { name: 'kick', detectable: 5, matched: 5 },
    { name: 'hat', detectable: 0, matched: 0 },
  ],
}

describe('metricRows', () => {
  it('turns the analysis metrics into labelled values', () => {
    expect(metricRows(METRICS)).toEqual([
      { label: '峰值', value: '-1.0 dBFS' },
      { label: '整体响度（RMS）', value: '-12.2 dBFS' },
      { label: '削波样本', value: '0' },
      { label: '起音对齐网格', value: '87%' },
      { label: '检测到的起音', value: '56' },
    ])
  })

  it('leaves out what is missing or not a number, and copes with null', () => {
    expect(metricRows(null)).toEqual([])
    expect(metricRows({ peak_dbfs: 'x', grid_alignment: null, onsets: 3 })).toEqual([
      { label: '检测到的起音', value: '3' },
    ])
  })
})

describe('matchRows', () => {
  it('adds up the counts per event name and keeps first-seen order', () => {
    expect(matchRows(METRICS)).toEqual([
      { name: 'kick', matched: 14, detectable: 15 },
      { name: 'hat', matched: 0, detectable: 0 },
    ])
  })

  it('is empty for bad input', () => {
    expect(matchRows(null)).toEqual([])
    expect(matchRows({ event_matches: 'nope' })).toEqual([])
    expect(matchRows({ event_matches: [{ name: 1 }, null] })).toEqual([])
  })
})

describe('metricWarnings', () => {
  it('lists string warnings only', () => {
    expect(metricWarnings(METRICS)).toEqual(['整体 RMS 偏高', '另一条'])
    expect(metricWarnings({ warnings: [1, 'ok'] })).toEqual(['ok'])
    expect(metricWarnings(null)).toEqual([])
  })
})
