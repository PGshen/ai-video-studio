/**
 * 创建项目时「选视频类型」的纯逻辑（计划 pipeline-config T6）。
 *
 * 合法组合、可用性和流水线全部来自后端 `GET /api/video-kinds` 的 `kinds`；这里只做查找和展示，
 * 不复写合法性规则或流水线推导。
 */

import { STAGE_TITLES } from '@/composables/stageTitles'
import type {
  KindOptionOut,
  MusicSource,
  PresetOut,
  ProjectKindOut,
  VideoKind,
  VideoKindsOut,
} from '@/types/api'

const VIDEO_KIND_LABELS: Record<VideoKind, string> = {
  explainer_manim: '知识讲解（Manim，已下线）',
  explainer_html: '知识讲解（HTML）',
  motion_reel: '动态图形短片',
  music_video: '音乐 MV',
}

export const MUSIC_LABELS: Record<MusicSource, string> = {
  none: '无配乐',
  synth: '合成配乐',
  import: '导入音乐',
}

/** 某个预设 + 配乐对应的配置；不存在（后端没有这个组合）时返回 `undefined`。 */
export function findKind(
  kinds: KindOptionOut[],
  preset: PresetOut,
  music: MusicSource,
): KindOptionOut | undefined {
  return kinds.find((k) => k.video_kind === preset.video_kind && k.music_source === music)
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
export function initialSelection(data: VideoKindsOut): { videoKind: VideoKind; music: MusicSource } {
  for (const preset of data.presets) {
    for (const music of preset.music_choices) {
      if (findKind(data.kinds, preset, music)?.available) {
        return { videoKind: preset.video_kind, music }
      }
    }
  }
  const first = data.presets[0]
  return { videoKind: first.video_kind, music: first.default.music_source }
}

/** 流水线展示："选题 → 叙事 → 动画"。 */
export function pipelineText(pipeline: string[]): string {
  return pipeline.map((id) => STAGE_TITLES[id] ?? id).join(' → ')
}

/** 项目的类型摘要，例如"知识讲解（HTML）· 有旁白 · 无配乐"。 */
export function KIND_SUMMARY(kind: ProjectKindOut): string {
  const label = VIDEO_KIND_LABELS[kind.video_kind] ?? kind.video_kind
  // 全角右括号后不加空格（"知识讲解（HTML）· 有旁白"），其余用 " · " 分隔。
  const sep = label.endsWith('）') ? '· ' : ' · '
  const rest = [kind.narration ? '有旁白' : '无旁白', MUSIC_LABELS[kind.music_source]].join(' · ')
  return `${label}${sep}${rest}`
}
