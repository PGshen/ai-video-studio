/**
 * 配乐画布的坐标换算（纯函数）：时间 ↔ 横坐标、波形包络 → 条形、事件与段落 → 标记。
 * 不碰 DOM；组件把结果画在 canvas 或 SVG 上。时长或宽度不是正数时一律返回空或 0，
 * 非有限值按 0 处理，画布不会因为坏数据崩掉。
 */
import type { MusicEventOut, MusicSectionOut } from '@/types/api'

function finite(value: number): number {
  return Number.isFinite(value) ? value : 0
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

function usable(duration: number, width: number): boolean {
  return Number.isFinite(duration) && duration > 0 && Number.isFinite(width) && width > 0
}

/** `t` 秒在宽 `width`、时长 `duration` 的时间轴上的横坐标（夹在 0 到 `width`）。 */
export function timeToX(t: number, duration: number, width: number): number {
  if (!usable(duration, width)) return 0
  return (clamp(finite(t), 0, duration) / duration) * width
}

/** 横坐标 `x` 对应的时间（点击波形跳转用），夹在 0 到 `duration`。 */
export function xToTime(x: number, duration: number, width: number): number {
  if (!usable(duration, width)) return 0
  return (clamp(finite(x), 0, width) / width) * duration
}

export interface PeakBar {
  x: number
  width: number
  top: number
  bottom: number
}

/** 包络（每点 0–1 的峰值）→ 围绕垂直中线的对称条形，每点一条，铺满 `width`。 */
export function waveformPeaks(points: readonly number[], width: number, height: number): PeakBar[] {
  if (points.length === 0 || !(width > 0) || !(height > 0)) return []
  const barWidth = width / points.length
  const middle = height / 2
  return points.map((point, index) => {
    const half = clamp(finite(point), 0, 1) * middle
    return { x: index * barWidth, width: barWidth, top: middle - half, bottom: middle + half }
  })
}

export interface EventMarker {
  name: string
  kind: string
  x: number
  /** 瞬发事件为 0（画一条线）；扫频是起止之间的宽度。 */
  width: number
}

export function eventMarkers(
  events: readonly MusicEventOut[],
  duration: number,
  width: number,
): EventMarker[] {
  if (!usable(duration, width)) return []
  return events.map((event) => {
    const x = timeToX(event.start, duration, width)
    const end = timeToX(event.end, duration, width)
    return {
      name: event.name,
      kind: event.kind,
      x,
      width: event.kind === 'sweep' ? Math.max(0, end - x) : 0,
    }
  })
}

export interface SectionBand {
  id: string
  label: string
  x: number
  width: number
}

export function sectionBands(
  sections: readonly MusicSectionOut[],
  duration: number,
  width: number,
): SectionBand[] {
  if (!usable(duration, width)) return []
  return sections.map((section) => {
    const x = timeToX(section.start, duration, width)
    return {
      id: section.id,
      label: section.label,
      x,
      width: Math.max(0, timeToX(section.end, duration, width) - x),
    }
  })
}
