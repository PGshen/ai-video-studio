/**
 * 测试用的 `GET /api/video-kinds` 响应：HTML 讲解（html/true/none）与音乐视频（html/false/import）可用，
 * 其余分阶段配置按"阶段尚未实现"禁用；自由模式（free-mode）的四种配置与完全自由（open-mode）都可用。
 */
import type { KindOptionOut, PresetOut, VideoKindsOut } from '@/types/api'

const REASON = '该类型的阶段尚未实现'

function kind(
  video_kind: KindOptionOut['video_kind'],
  engine: KindOptionOut['engine'],
  narration: boolean,
  music_source: KindOptionOut['music_source'],
  pipeline: string[],
  available = false,
  mode: KindOptionOut['mode'] = 'staged',
): KindOptionOut {
  return {
    engine,
    narration,
    music_source,
    mode,
    video_kind,
    pipeline,
    available,
    unavailable_reason: available ? null : REASON,
  }
}

const EXPLAINER = ['topic', 'narrative']

export const VIDEO_KINDS_FIXTURE: VideoKindsOut = {
  presets: [
    {
      video_kind: 'explainer_html',
      label: '知识讲解（HTML）',
      description: '有旁白的知识讲解，HTML 动画',
      music_choices: ['none', 'synth', 'import'],
      default: { engine: 'html', narration: true, music_source: 'none', mode: 'staged' },
    },
    {
      video_kind: 'motion_reel',
      label: '动态短片',
      description: '无旁白，合成配乐',
      music_choices: ['synth'],
      default: { engine: 'html', narration: false, music_source: 'synth', mode: 'staged' },
    },
    {
      video_kind: 'music_video',
      label: '音乐视频',
      description: '无旁白，导入音乐',
      music_choices: ['import'],
      default: { engine: 'html', narration: false, music_source: 'import', mode: 'staged' },
    },
    {
      video_kind: 'explainer_html',
      label: '自由讲解',
      description: '给一个题目直接做讲解视频',
      music_choices: ['none', 'synth'],
      default: { engine: 'html', narration: true, music_source: 'none', mode: 'free' },
    },
    {
      video_kind: 'motion_reel',
      label: '自由短片',
      description: '临时做一条短片',
      music_choices: ['synth'],
      default: { engine: 'html', narration: false, music_source: 'synth', mode: 'free' },
    },
    {
      video_kind: 'music_video',
      label: '自由 MV',
      description: '上传一首歌直接做 MV',
      music_choices: ['import'],
      default: { engine: 'html', narration: false, music_source: 'import', mode: 'free' },
    },
    {
      video_kind: 'open',
      label: '完全自由',
      description: '没有结构和检查，像直接用 Claude Code 一样',
      music_choices: ['none'],
      default: { engine: 'html', narration: false, music_source: 'none', mode: 'open' },
    },
  ] satisfies PresetOut[],
  kinds: [
    kind('explainer_html', 'html', true, 'none', [...EXPLAINER, 'animation_html'], true),
    kind('explainer_html', 'html', true, 'synth', [...EXPLAINER, 'music', 'animation_html']),
    kind('explainer_html', 'html', true, 'import', [...EXPLAINER, 'music', 'animation_html']),
    kind('motion_reel', 'html', false, 'synth', ['concept', 'produce']),
    kind('music_video', 'html', false, 'import', ['concept', 'produce'], true),
    kind('explainer_html', 'html', true, 'none', ['free_explainer'], true, 'free'),
    kind('explainer_html', 'html', true, 'synth', ['free_explainer'], true, 'free'),
    kind('motion_reel', 'html', false, 'synth', ['free_produce'], true, 'free'),
    kind('music_video', 'html', false, 'import', ['free_produce'], true, 'free'),
    kind('open', 'html', false, 'none', ['open'], true, 'open'),
  ],
}
