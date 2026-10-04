/** 测试用的 `GET /api/video-kinds` 响应：与后端默认注册表一致，只有 manim/true/none 可用。 */
import type { KindOptionOut, PresetOut, VideoKindsOut } from '@/types/api'

const REASON = '该类型的阶段尚未实现'

function kind(
  video_kind: KindOptionOut['video_kind'],
  engine: KindOptionOut['engine'],
  narration: boolean,
  music_source: KindOptionOut['music_source'],
  pipeline: string[],
  available = false,
): KindOptionOut {
  return {
    engine,
    narration,
    music_source,
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
      video_kind: 'explainer_manim',
      label: '知识讲解（Manim）',
      description: '有旁白的知识讲解，Manim 动画',
      music_choices: ['none', 'synth', 'import'],
      default: { engine: 'manim', narration: true, music_source: 'none' },
    },
    {
      video_kind: 'explainer_html',
      label: '知识讲解（HTML）',
      description: '有旁白的知识讲解，HTML 动画',
      music_choices: ['none', 'synth', 'import'],
      default: { engine: 'html', narration: true, music_source: 'none' },
    },
    {
      video_kind: 'motion_reel',
      label: '动态短片',
      description: '无旁白，合成配乐',
      music_choices: ['synth'],
      default: { engine: 'html', narration: false, music_source: 'synth' },
    },
    {
      video_kind: 'music_video',
      label: '音乐视频',
      description: '无旁白，导入音乐',
      music_choices: ['import'],
      default: { engine: 'html', narration: false, music_source: 'import' },
    },
  ] satisfies PresetOut[],
  kinds: [
    kind('explainer_manim', 'manim', true, 'none', [...EXPLAINER, 'animation'], true),
    kind('explainer_manim', 'manim', true, 'synth', [...EXPLAINER, 'music', 'animation']),
    kind('explainer_manim', 'manim', true, 'import', [...EXPLAINER, 'music', 'animation']),
    kind('explainer_html', 'html', true, 'none', [...EXPLAINER, 'animation_html']),
    kind('explainer_html', 'html', true, 'synth', [...EXPLAINER, 'music', 'animation_html']),
    kind('explainer_html', 'html', true, 'import', [...EXPLAINER, 'music', 'animation_html']),
    kind('motion_reel', 'html', false, 'synth', ['concept', 'beatsheet', 'music', 'animation_html']),
    kind('music_video', 'html', false, 'import', ['concept', 'music', 'beatsheet', 'animation_html']),
  ],
}
