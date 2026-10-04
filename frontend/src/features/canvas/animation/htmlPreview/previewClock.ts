/**
 * 实时预览的时间换算（纯函数）：全局时间 ↔ 镜头内时间、镜头刻度、循环与回退计时。
 * 播放时钟优先用当前镜头配音的 `currentTime` 加镜头起点；某个镜头没有配音时回退为
 * 墙钟计时（`advanceClock`）。预览与成片的音画对齐允许有小偏差，以成片为准。
 */
import type { HtmlPreviewAudio, HtmlPreviewSection } from '@/types/api'

/** `t` 所在镜头的下标（越界夹紧到首尾；没有镜头返回 -1）。 */
export function sectionAt(sections: readonly HtmlPreviewSection[], t: number): number {
  if (sections.length === 0) return -1
  const index = sections.findIndex((section) => t >= section.start && t < section.end)
  if (index !== -1) return index
  return t < sections[0]!.start ? 0 : sections.length - 1
}

/** 当前镜头配音的 `currentTime`（镜头内秒）换成全局时间，夹在该镜头范围内。 */
export function globalTime(section: HtmlPreviewSection, localSeconds: number): number {
  return Math.min(section.end, Math.max(section.start, section.start + localSeconds))
}

/** 没有配音时按墙钟推进；到达总时长即结束。 */
export function advanceClock(
  t: number,
  deltaSeconds: number,
  duration: number,
): { t: number; ended: boolean } {
  const next = t + deltaSeconds
  return next >= duration ? { t: duration, ended: true } : { t: next, ended: false }
}

/** 循环当前镜头：走过镜头末尾就回到镜头起点。 */
export function loopedTime(section: HtmlPreviewSection, t: number, loop: boolean): number {
  return loop && t >= section.end ? section.start : t
}

export function nextSection(
  sections: readonly HtmlPreviewSection[],
  index: number,
): HtmlPreviewSection | null {
  return sections[index + 1] ?? null
}

/** 进度条上相邻镜头的分界位置（占总时长的百分比）。 */
export function sectionTicks(sections: readonly HtmlPreviewSection[], duration: number): number[] {
  if (duration <= 0) return []
  return sections.slice(1).map((section) => (section.start / duration) * 100)
}

export function hasAudio(audio: readonly HtmlPreviewAudio[], sectionId: string): boolean {
  return audio.some((item) => item.section_id === sectionId)
}

/** `meta.hash` 真的变了才重载 iframe（`workspace_changed` 很频繁，大多不影响预览）。 */
export function shouldReloadPreview(
  loadedHash: string | null,
  latestHash: string | undefined,
): boolean {
  return latestHash !== undefined && latestHash !== loadedHash
}
