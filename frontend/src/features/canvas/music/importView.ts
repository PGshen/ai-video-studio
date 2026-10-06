/**
 * 导入音乐画布的展示换算（纯函数，不碰 DOM）。坐标一律以**整曲时间**为轴：能量曲线与网格取整曲，
 * 截取区间与段落是叠加层。时长或宽度不是正数、BPM 不是正数时返回空，坏数据不会让画布崩。
 */
import type {
  LyricLineOut,
  MusicEnergyOut,
  MusicGridOut,
  MusicMetaOut,
  MusicRangeOut,
  MusicSectionOut,
} from '@/types/api'
import { formatClock } from './musicView'
import { sectionBands, timeToX, waveformPeaks, type PeakBar, type SectionBand } from './waveform'

/** 与后端 `api.music_import.MAX_UPLOAD_BYTES`、`stages.common.music_source.SOURCE_EXTENSIONS` 一致。 */
export const MAX_UPLOAD_BYTES = 150 * 1024 * 1024
export const SOURCE_EXTENSIONS = ['mp3', 'wav', 'm4a', 'flac', 'ogg'] as const
/** 与后端 `timeline.lyrics.MAX_LRC_BYTES` 一致。 */
export const MAX_LYRICS_BYTES = 200_000

const BEATS_PER_BAR = 4
const MIN_LINE_GAP_PX = 4
const CONFIDENCE_WARN = 0.5

export interface GridLine {
  x: number
  strong: boolean
}

function positive(value: number): boolean {
  return Number.isFinite(value) && value > 0
}

/**
 * 区间内（无区间则整曲）的拍线：每拍一条细线，每 4 拍（强拍，`offset` 是第一个强拍）一条粗线。
 * 拍线的像素间隔小于 4 px 时只留强拍；强拍也过密时按小节抽稀到间隔不小于 4 px。
 */
export function gridLines(
  grid: MusicGridOut,
  range: MusicRangeOut | null,
  duration: number,
  width: number,
): GridLine[] {
  if (!positive(duration) || !positive(width) || !positive(grid.bpm) || !Number.isFinite(grid.offset)) {
    return []
  }
  const beat = 60 / grid.bpm
  const low = range ? Math.max(0, range.start) : 0
  const high = range ? Math.min(duration, range.end) : duration
  const beatPx = (beat / duration) * width
  const barPx = beatPx * BEATS_PER_BAR
  const barStride = barPx >= MIN_LINE_GAP_PX ? 1 : Math.ceil(MIN_LINE_GAP_PX / barPx)
  const first = Math.ceil((low - grid.offset) / beat - 1e-9)
  const last = Math.floor((high - grid.offset) / beat + 1e-9)
  const lines: GridLine[] = []
  for (let k = first; k <= last; k++) {
    const strong = ((k % BEATS_PER_BAR) + BEATS_PER_BAR) % BEATS_PER_BAR === 0
    if (beatPx < MIN_LINE_GAP_PX) {
      if (!strong) continue
      const bar = Math.round(k / BEATS_PER_BAR)
      if (((bar % barStride) + barStride) % barStride !== 0) continue
    }
    lines.push({ x: timeToX(grid.offset + k * beat, duration, width), strong })
  }
  return lines
}

/** 能量曲线按最大值归一化后复用波形的条形（对称于水平中线）。 */
export function energyBars(energy: MusicEnergyOut, width: number, height: number): PeakBar[] {
  const peak = energy.values.reduce((max, v) => (Number.isFinite(v) && v > max ? v : max), 0)
  const normalised = energy.values.map((v) => (peak > 0 && Number.isFinite(v) ? v / peak : 0))
  return waveformPeaks(normalised, width, height)
}

export interface RangeMask {
  left: { x: number; width: number }
  right: { x: number; width: number }
}

/** 截取区间外两侧的遮罩；没有区间或时长/宽度无效时为 `null`。 */
export function rangeMask(
  range: MusicRangeOut | null,
  duration: number,
  width: number,
): RangeMask | null {
  if (!range || !positive(duration) || !positive(width)) return null
  const start = timeToX(range.start, duration, width)
  const end = timeToX(range.end, duration, width)
  return { left: { x: 0, width: start }, right: { x: end, width: Math.max(0, width - end) } }
}

export function sectionBandsFromMeta(
  sections: readonly MusicSectionOut[],
  duration: number,
  width: number,
): SectionBand[] {
  return sectionBands(sections, duration, width)
}

export interface SummaryRow {
  label: string
  value: string
  /** 需要用户留意（置信度低、有警告）。 */
  attention: boolean
}

export function analysisRows(meta: MusicMetaOut): SummaryRow[] {
  const analysis = meta.analysis
  if (!analysis) return []
  const rows: SummaryRow[] = [
    { label: 'BPM', value: String(analysis.bpm), attention: false },
    {
      label: '置信度',
      value: analysis.confidence.toFixed(2),
      attention: analysis.confidence < CONFIDENCE_WARN,
    },
    { label: '拟合残差', value: `${analysis.residual_ms.toFixed(1)} ms`, attention: false },
    { label: '时长', value: formatClock(analysis.duration), attention: false },
  ]
  if (analysis.warnings.length > 0) {
    rows.push({ label: '警告', value: analysis.warnings.join('；'), attention: true })
  }
  return rows
}

/** 客户端先挡一道（服务端为准）：返回中文提示，通过时为 `null`。 */
export function checkSourceFile(file: Pick<File, 'name' | 'size'>): string | null {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : ''
  if (!(SOURCE_EXTENSIONS as readonly string[]).includes(ext)) {
    return `不支持的音频格式，请上传 ${SOURCE_EXTENSIONS.join(' / ')}`
  }
  if (file.size === 0) return '文件是空的'
  if (file.size > MAX_UPLOAD_BYTES) return `文件超过上限 ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB`
  return null
}

/** 项目设置里 `music_source === 'import'`：音乐阶段用导入形态的画布。 */
export function isImportMusic(settings: Record<string, unknown> | null | undefined): boolean {
  return settings?.music_source === 'import'
}

/** 歌词文件的客户端检查（服务端为准）：返回中文提示，通过时为 `null`。 */
export function checkLyricsFile(file: Pick<File, 'name' | 'size'>): string | null {
  if (!file.name.toLowerCase().endsWith('.lrc')) return '歌词文件需要是 .lrc（带时间戳的 LRC）'
  if (file.size === 0) return '文件是空的'
  if (file.size > MAX_LYRICS_BYTES) return `文件超过上限 ${MAX_LYRICS_BYTES / 1000} KB`
  return null
}

/** 播放位置 `time` 对应的歌词行下标：正在唱的那一句，句间空隙里是上一句，第一句之前为 -1。 */
export function lyricAt(lines: readonly LyricLineOut[], time: number): number {
  let found = -1
  for (let i = 0; i < lines.length; i++) {
    if (lines[i]!.start <= time) found = i
    else break
  }
  return found
}
