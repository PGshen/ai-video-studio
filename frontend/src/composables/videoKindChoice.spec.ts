import { describe, expect, it } from 'vitest'
import { VIDEO_KINDS_FIXTURE as DATA } from '@/test/videoKindsFixture'
import {
  findKind,
  initialSelection,
  freeFormLabel,
  KIND_SUMMARY,
  kindFields,
  presetAvailability,
  presetKey,
  presetsFor,
} from './videoKindChoice'

const preset = (key: string) => DATA.presets.find((p) => presetKey(p) === key)!

describe('videoKindChoice', () => {
  it('只有 html/true/none 可用时初始选中 HTML 讲解 + 无配乐', () => {
    expect(initialSelection(DATA)).toEqual({ preset: 'explainer_html', music: 'none' })
  })

  it('跳过整体不可用的预设，选第一个有可用配置的', () => {
    const data = {
      ...DATA,
      kinds: DATA.kinds.map((k) =>
        k.mode === 'free'
          ? k
          : k.video_kind === 'explainer_html'
            ? { ...k, available: false }
            : k.video_kind === 'motion_reel'
              ? { ...k, available: true }
              : k,
      ),
    }
    expect(initialSelection(data)).toEqual({ preset: 'motion_reel', music: 'synth' })
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

  it('presetKey 区分分阶段与自由的同类预设', () => {
    expect(DATA.presets.map(presetKey)).toEqual([
      'explainer_html',
      'motion_reel',
      'music_video',
      'free-explainer_html',
      'free-motion_reel',
      'free-music_video',
      'open',
    ])
  })

  it('presetsFor 只留给定模式的预设；initialSelection 在其中挑', () => {
    expect(presetsFor(DATA, ['free']).presets.map(presetKey)).toEqual([
      'free-explainer_html',
      'free-motion_reel',
      'free-music_video',
    ])
    expect(initialSelection(presetsFor(DATA, ['free']))).toEqual({
      preset: 'free-explainer_html',
      music: 'none',
    })
  })

  it('findKind 按模式区分：自由讲解 + 合成配乐对应单阶段流水线', () => {
    expect(findKind(DATA.kinds, preset('free-explainer_html'), 'synth')?.pipeline).toEqual([
      'free_explainer',
    ])
    expect(findKind(DATA.kinds, preset('explainer_html'), 'synth')?.pipeline).toContain('music')
    expect(findKind(DATA.kinds, preset('free-explainer_html'), 'import')).toBeUndefined()
  })

  it('KIND_SUMMARY 给自由项目加上「自由模式」', () => {
    expect(
      KIND_SUMMARY({
        video_kind: 'motion_reel',
        engine: 'html',
        narration: false,
        music_source: 'synth',
        mode: 'free',
        pipeline: ['free_produce'],
      }),
    ).toBe('自由模式 · 动态图形短片 · 无旁白 · 合成配乐')
  })

  it('KIND_SUMMARY 对完全自由项目只写「完全自由」（形态字段是占位）', () => {
    expect(
      KIND_SUMMARY({
        video_kind: 'open',
        engine: 'html',
        narration: false,
        music_source: 'none',
        mode: 'open',
        pipeline: ['open'],
      }),
    ).toBe('完全自由')
  })

  it('kindFields：完全自由只给 mode，其余模式给出完整形态', () => {
    const open = findKind(DATA.kinds, preset('open'), 'none')!
    expect(kindFields(open)).toEqual({ mode: 'open' })
    const reel = findKind(DATA.kinds, preset('free-motion_reel'), 'synth')!
    expect(kindFields(reel)).toEqual({
      engine: 'html',
      narration: false,
      music_source: 'synth',
      mode: 'free',
    })
  })

  it('KIND_SUMMARY 拼出类型、旁白、配乐', () => {
    const summary = KIND_SUMMARY
    expect(summary({ video_kind: 'explainer_manim', engine: 'manim', narration: true, music_source: 'none', mode: 'staged', pipeline: [] })).toBe(
      '知识讲解（Manim，已下线）· 有旁白 · 无配乐',
    )
    expect(summary({ video_kind: 'explainer_html', engine: 'html', narration: true, music_source: 'synth', mode: 'staged', pipeline: [] })).toBe(
      '知识讲解（HTML）· 有旁白 · 合成配乐',
    )
    expect(summary({ video_kind: 'motion_reel', engine: 'html', narration: false, music_source: 'synth', mode: 'staged', pipeline: [] })).toBe(
      '动态图形短片 · 无旁白 · 合成配乐',
    )
    expect(summary({ video_kind: 'music_video', engine: 'html', narration: false, music_source: 'import', mode: 'staged', pipeline: [] })).toBe(
      '音乐 MV · 无旁白 · 导入音乐',
    )
  })

  it('freeFormLabel：讲解（可带背景乐）/ 短片 / MV', () => {
    const base = { engine: 'html' as const, mode: 'free' as const, pipeline: [] }
    expect(freeFormLabel({ ...base, video_kind: 'explainer_html', narration: true, music_source: 'none' })).toBe('讲解')
    expect(freeFormLabel({ ...base, video_kind: 'explainer_html', narration: true, music_source: 'synth' })).toBe(
      '讲解（带背景乐）',
    )
    expect(freeFormLabel({ ...base, video_kind: 'motion_reel', narration: false, music_source: 'synth' })).toBe('短片')
    expect(freeFormLabel({ ...base, video_kind: 'music_video', narration: false, music_source: 'import' })).toBe('MV')
  })
})
