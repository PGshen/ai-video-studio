import { describe, expect, it } from 'vitest'
import { VIDEO_KINDS_FIXTURE as DATA } from '@/test/videoKindsFixture'
import { findKind, initialSelection, KIND_SUMMARY, presetAvailability } from './videoKindChoice'

const preset = (k: string) => DATA.presets.find((p) => p.video_kind === k)!

describe('videoKindChoice', () => {
  it('只有 html/true/none 可用时初始选中 HTML 讲解 + 无配乐', () => {
    expect(initialSelection(DATA)).toEqual({ videoKind: 'explainer_html', music: 'none' })
  })

  it('跳过整体不可用的预设，选第一个有可用配置的', () => {
    const data = {
      ...DATA,
      kinds: DATA.kinds.map((k) =>
        k.video_kind === 'explainer_html' ? { ...k, available: false } : k.video_kind === 'motion_reel' ? { ...k, available: true } : k,
      ),
    }
    expect(initialSelection(data)).toEqual({ videoKind: 'motion_reel', music: 'synth' })
  })

  it('presetAvailability：短片不可用并带原因；HTML 讲解只要有一个配乐可用就可用', () => {
    expect(presetAvailability(DATA, preset('motion_reel'))).toEqual({
      available: false,
      reason: '该类型的阶段尚未实现',
    })
    expect(presetAvailability(DATA, preset('explainer_html'))).toEqual({ available: true, reason: null })
  })

  it('findKind 按预设和配乐找到对应配置', () => {
    const found = findKind(DATA.kinds, preset('explainer_html'), 'synth')
    expect(found?.engine).toBe('html')
    expect(found?.music_source).toBe('synth')
    expect(findKind(DATA.kinds, preset('motion_reel'), 'none')).toBeUndefined()
  })

  it('KIND_SUMMARY 拼出类型、旁白、配乐', () => {
    const summary = KIND_SUMMARY
    expect(summary({ video_kind: 'explainer_manim', engine: 'manim', narration: true, music_source: 'none', pipeline: [] })).toBe(
      '知识讲解（Manim，已下线）· 有旁白 · 无配乐',
    )
    expect(summary({ video_kind: 'explainer_html', engine: 'html', narration: true, music_source: 'synth', pipeline: [] })).toBe(
      '知识讲解（HTML）· 有旁白 · 合成配乐',
    )
    expect(summary({ video_kind: 'motion_reel', engine: 'html', narration: false, music_source: 'synth', pipeline: [] })).toBe(
      '动态图形短片 · 无旁白 · 合成配乐',
    )
    expect(summary({ video_kind: 'music_video', engine: 'html', narration: false, music_source: 'import', pipeline: [] })).toBe(
      '音乐 MV · 无旁白 · 导入音乐',
    )
  })
})
