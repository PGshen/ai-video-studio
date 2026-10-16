/**
 * 创建项目时「选视频类型」的纯逻辑（计划 pipeline-config T6）。
 *
 * 合法组合、可用性和流水线全部来自后端 `GET /api/video-kinds` 的 `kinds`；这里只做查找和展示，
 * 不复写合法性规则或流水线推导。
 */

import { STAGE_TITLES } from '@/composables/stageTitles'
import type {
  KindOptionOut,
  Mode,
  MusicSource,
  PresetOut,
  ProjectCreate,
  ProjectKindOut,
  VideoKind,
  VideoKindsOut,
} from '@/types/api'

const VIDEO_KIND_LABELS: Record<VideoKind, string> = {
  explainer_manim: '知识讲解（Manim，已下线）',
  explainer_html: '知识讲解（HTML）',
  motion_reel: '动态图形短片',
  music_video: '音乐 MV',
  open: '完全自由',
}

export const MUSIC_LABELS: Record<MusicSource, string> = {
  none: '无配乐',
  synth: '合成配乐',
  import: '导入音乐',
}

/**
 * 预设的唯一键：分阶段与自由模式各有一个同 `video_kind` 的预设，单靠 `video_kind` 分不开。
 * 分阶段预设沿用 `video_kind`（如 `explainer_html`），自由预设加前缀（`free-explainer_html`）。
 */
export function presetKey(preset: PresetOut): string {
  return preset.default.mode === 'free' ? `free-${preset.video_kind}` : preset.video_kind
}

/** 只保留给定模式的预设与配置（项目页的新建只给自由模式）。 */
export function presetsFor(data: VideoKindsOut, modes: readonly Mode[]): VideoKindsOut {
  return {
    presets: data.presets.filter((p) => modes.includes(p.default.mode)),
    kinds: data.kinds.filter((k) => modes.includes(k.mode)),
  }
}

/** 某个预设 + 配乐对应的配置；不存在（后端没有这个组合）时返回 `undefined`。 */
export function findKind(
  kinds: KindOptionOut[],
  preset: PresetOut,
  music: MusicSource,
): KindOptionOut | undefined {
  return kinds.find(
    (k) =>
      k.video_kind === preset.video_kind && k.music_source === music && k.mode === preset.default.mode,
  )
}

/** 预设下任一配乐选项可用即可用；全部不可用时取第一条原因。 */
export function presetAvailability(
  data: VideoKindsOut,
  preset: PresetOut,
): { available: boolean; reason: string | null } {
  const options = preset.music_choices
    .map((music) => findKind(data.kinds, preset, music))
    .filter((k): k is KindOptionOut => k !== undefined)
  if (options.some((k) => k.available)) return { available: true, reason: null }
  return { available: false, reason: options.find((k) => k.unavailable_reason)?.unavailable_reason ?? null }
}

/** 第一个有可用配置的预设，配乐取该预设下第一个可用选项；一个都不可用时退回第一个预设的默认。 */
export function initialSelection(data: VideoKindsOut): { preset: string; music: MusicSource } {
  for (const preset of data.presets) {
    for (const music of preset.music_choices) {
      if (findKind(data.kinds, preset, music)?.available) {
        return { preset: presetKey(preset), music }
      }
    }
  }
  const first = data.presets[0]
  return { preset: presetKey(first), music: first.default.music_source }
}

/** 预设键 + 配乐 → 配置；找不到返回 `undefined`。 */
export function selectedKind(
  data: VideoKindsOut,
  key: string,
  music: MusicSource,
): KindOptionOut | undefined {
  const preset = data.presets.find((p) => presetKey(p) === key)
  return preset ? findKind(data.kinds, preset, music) : undefined
}

/**
 * 创建请求里的类型字段：完全自由只给 `mode`（后端拒绝它带形态字段，open-mode 设计 §3.2），
 * 其它模式给出完整的 engine/narration/music_source/mode。
 */
export function kindFields(
  kind: KindOptionOut,
): Pick<ProjectCreate, 'engine' | 'narration' | 'music_source' | 'mode'> {
  if (kind.mode === 'open') return { mode: 'open' }
  return {
    engine: kind.engine,
    narration: kind.narration,
    music_source: kind.music_source,
    mode: kind.mode,
  }
}

/** 流水线展示："选题 → 叙事 → 动画"。 */
export function pipelineText(pipeline: string[]): string {
  return pipeline.map((id) => STAGE_TITLES[id] ?? id).join(' → ')
}

/** 项目的类型摘要，例如"知识讲解（HTML）· 有旁白 · 无配乐"。 */
export function KIND_SUMMARY(kind: ProjectKindOut): string {
  // Open-mode form fields are placeholders (open-mode design §3.1): say nothing about them.
  if (kind.mode === 'open') return VIDEO_KIND_LABELS.open
  const label = VIDEO_KIND_LABELS[kind.video_kind] ?? kind.video_kind
  // 全角右括号后不加空格（"知识讲解（HTML）· 有旁白"），其余用 " · " 分隔。
  const sep = label.endsWith('）') ? '· ' : ' · '
  const rest = [kind.narration ? '有旁白' : '无旁白', MUSIC_LABELS[kind.music_source]].join(' · ')
  const prefix = kind.mode === 'free' ? '自由模式 · ' : ''
  return `${prefix}${label}${sep}${rest}`
}

/** 自由项目的形态短名：讲解（可带背景乐）、短片、MV（工作台左侧的「自由模式 · …」）。 */
export function freeFormLabel(kind: ProjectKindOut): string {
  if (kind.narration) return kind.music_source === 'synth' ? '讲解（带背景乐）' : '讲解'
  return kind.music_source === 'import' ? 'MV' : '短片'
}
