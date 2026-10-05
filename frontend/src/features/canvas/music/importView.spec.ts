import { describe, expect, it } from 'vitest'
import type { MusicMetaOut } from '@/types/api'
import {
  MAX_UPLOAD_BYTES,
  analysisRows,
  checkSourceFile,
  energyBars,
  gridLines,
  isImportMusic,
  rangeMask,
  sectionBandsFromMeta,
} from './importView'

const GRID = { bpm: 120, offset: 0.5, downbeats: [0.5, 2.5, 4.5] }

describe('gridLines', () => {
  it('每拍一条线，每 4 拍（强拍）标成粗线，x 按整曲时间换算', () => {
    // 20 s on 1000 px = 50 px/s; beat = 0.5 s = 25 px
    const lines = gridLines(GRID, null, 20, 1000)
    expect(lines[0]).toEqual({ x: 0, strong: false }) // k = -1: the beat before the first downbeat
    expect(lines[1]).toEqual({ x: 25, strong: true })
    expect(lines[2]).toEqual({ x: 50, strong: false })
    expect(lines[5]).toEqual({ x: 125, strong: true })
    expect(lines.filter((l) => l.strong).map((l) => l.x).slice(0, 3)).toEqual([25, 125, 225])
  })

  it('offset 之前的拍也画（k 可为负），强拍相位不变', () => {
    const lines = gridLines({ bpm: 120, offset: 1.5, downbeats: [] }, null, 4, 400)
    // beats at 0.0 (k=-3), 0.5, 1.0, 1.5(strong), ...
    expect(lines.map((l) => l.x).slice(0, 4)).toEqual([0, 50, 100, 150])
    expect(lines.map((l) => l.strong).slice(0, 4)).toEqual([false, false, false, true])
  })

  it('只画区间内的线（含两端）', () => {
    const lines = gridLines(GRID, { start: 4.5, end: 8.5 }, 20, 1000)
    expect(lines[0]!.x).toBe(225)
    expect(lines[lines.length - 1]!.x).toBe(425)
    expect(lines.every((l) => l.x >= 225 && l.x <= 425)).toBe(true)
  })

  it('拍线过密时只留强拍；强拍也过密时按小节抽稀', () => {
    const dense = gridLines(GRID, null, 20, 100) // 5 px/s → beat 2.5 px < 4 px, bar 10 px
    expect(dense.length).toBeGreaterThan(0)
    expect(dense.every((l) => l.strong)).toBe(true)
    const denser = gridLines(GRID, null, 20, 40) // bar = 4 px... bar 4 px not < 4
    expect(denser.every((l) => l.strong)).toBe(true)
    const tiny = gridLines(GRID, null, 20, 20) // bar 2 px < 4 px → every 2nd bar
    const xs = tiny.map((l) => l.x)
    for (let i = 1; i < xs.length; i++) expect(xs[i]! - xs[i - 1]!).toBeGreaterThanOrEqual(4)
  })

  it('坏输入返回空', () => {
    expect(gridLines(GRID, null, 0, 1000)).toEqual([])
    expect(gridLines(GRID, null, 20, 0)).toEqual([])
    expect(gridLines({ bpm: 0, offset: 0, downbeats: [] }, null, 20, 1000)).toEqual([])
    expect(gridLines({ bpm: Number.NaN, offset: 0, downbeats: [] }, null, 20, 1000)).toEqual([])
  })
})

describe('energyBars', () => {
  it('按最大值归一化后复用波形条形，每点一条铺满宽度', () => {
    const bars = energyBars({ hop: 0.1, values: [0, 0.5, 1] }, 300, 100)
    expect(bars).toHaveLength(3)
    expect(bars[2]!.top).toBe(0)
    expect(bars[2]!.bottom).toBe(100)
    expect(bars[1]!.top).toBe(25)
    expect(bars[0]!.x).toBe(0)
    expect(bars[1]!.width).toBe(100)
  })

  it('全零或空曲线不崩', () => {
    expect(energyBars({ hop: 0.1, values: [] }, 300, 100)).toEqual([])
    const flat = energyBars({ hop: 0.1, values: [0, 0] }, 300, 100)
    expect(flat.every((b) => b.top === 50 && b.bottom === 50)).toBe(true)
  })
})

describe('rangeMask', () => {
  it('区间外两侧各一块遮罩，坐标按整曲时间', () => {
    expect(rangeMask({ start: 4.5, end: 18.5 }, 20, 1000)).toEqual({
      left: { x: 0, width: 225 },
      right: { x: 925, width: 75 },
    })
  })

  it('区间从 0 开始或到曲末时对应一侧宽度为 0', () => {
    expect(rangeMask({ start: 0, end: 10 }, 20, 1000)!.left.width).toBe(0)
    expect(rangeMask({ start: 10, end: 20 }, 20, 1000)!.right.width).toBe(0)
  })

  it('没有区间或坏时长返回 null', () => {
    expect(rangeMask(null, 20, 1000)).toBeNull()
    expect(rangeMask({ start: 0, end: 1 }, 0, 1000)).toBeNull()
  })
})

describe('sectionBandsFromMeta', () => {
  it('段落是整曲秒，按整曲换算', () => {
    const bands = sectionBandsFromMeta(
      [
        { id: 'a', label: 'intro', start: 0.5, end: 4.5 },
        { id: 'b', label: 'verse', start: 4.5, end: 12.5 },
      ],
      20,
      1000,
    )
    expect(bands).toEqual([
      { id: 'a', label: 'intro', x: 25, width: 200 },
      { id: 'b', label: 'verse', x: 225, width: 400 },
    ])
  })
})

function meta(over: Partial<MusicMetaOut>): MusicMetaOut {
  return {
    form: 'import',
    rendered: true,
    stale: false,
    hash: 'h',
    duration: 200.5,
    bpm: null,
    events: [],
    sections: [],
    waveform: [],
    metrics: null,
    source: null,
    analysis: null,
    grid: null,
    range: null,
    energy: null,
    sections_check: null,
    ...over,
  }
}

describe('analysisRows', () => {
  it('没有分析时没有行', () => {
    expect(analysisRows(meta({}))).toEqual([])
  })

  it('BPM、置信度、拟合残差、时长；正常时都不标注意', () => {
    const rows = analysisRows(
      meta({
        analysis: { bpm: 76.9, confidence: 0.84, residual_ms: 14, duration: 200.5, warnings: [] },
      }),
    )
    expect(rows.map((r) => [r.label, r.value, r.attention])).toEqual([
      ['BPM', '76.9', false],
      ['置信度', '0.84', false],
      ['拟合残差', '14.0 ms', false],
      ['时长', '3:20.5', false],
    ])
  })

  it('置信度低于 0.5 标注意；有警告时警告行也标注意', () => {
    const rows = analysisRows(
      meta({
        analysis: { bpm: 100, confidence: 0.3, residual_ms: 80, duration: 60, warnings: ['拍点不稳'] },
      }),
    )
    expect(rows.find((r) => r.label === '置信度')!.attention).toBe(true)
    expect(rows.find((r) => r.label === '警告')).toEqual({ label: '警告', value: '拍点不稳', attention: true })
  })
})

describe('checkSourceFile', () => {
  const file = (name: string, size = 10) => ({ name, size }) as File

  it('白名单扩展名（不分大小写）通过', () => {
    for (const name of ['a.mp3', 'a.WAV', 'x.m4a', 'x.flac', 'x.ogg', '我的 歌.Mp3']) {
      expect(checkSourceFile(file(name))).toBeNull()
    }
  })

  it('不支持的扩展名与没有扩展名给出中文提示', () => {
    expect(checkSourceFile(file('a.mp4'))).toContain('格式')
    expect(checkSourceFile(file('noext'))).toContain('格式')
  })

  it('大小：恰好等于上限通过，多 1 字节和空文件被拒', () => {
    expect(checkSourceFile(file('a.mp3', MAX_UPLOAD_BYTES))).toBeNull()
    expect(checkSourceFile(file('a.mp3', MAX_UPLOAD_BYTES + 1))).toContain('150 MB')
    expect(checkSourceFile(file('a.mp3', 0))).toContain('空')
  })
})

describe('isImportMusic', () => {
  it('只有 music_source 为 import 的项目走导入形态的画布', () => {
    expect(isImportMusic({ music_source: 'import' })).toBe(true)
    expect(isImportMusic({ music_source: 'synth' })).toBe(false)
    expect(isImportMusic({ music_source: 'none' })).toBe(false)
    expect(isImportMusic({})).toBe(false)
    expect(isImportMusic(null)).toBe(false)
    expect(isImportMusic(undefined)).toBe(false)
  })
})
