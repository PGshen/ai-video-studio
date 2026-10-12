import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { VIDEO_KINDS_FIXTURE } from '@/test/videoKindsFixture'
import type { Mode, MusicSource } from '@/types/api'
import VideoKindPicker from './VideoKindPicker.vue'

function mountPicker(
  preset = 'explainer_html',
  music: MusicSource = 'none',
  modes?: Mode[],
) {
  const wrapper = mount(VideoKindPicker, {
    props: {
      data: VIDEO_KINDS_FIXTURE,
      preset,
      music,
      ...(modes ? { modes } : {}),
      'onUpdate:preset': (value: string) => wrapper.setProps({ preset: value }),
      'onUpdate:music': (value: MusicSource) => wrapper.setProps({ music: value }),
    },
  })
  return wrapper
}
let w: ReturnType<typeof mountPicker>

describe('VideoKindPicker', () => {
  it('渲染三张预设卡片，不可用的禁用并显示原因', () => {
    w = mountPicker()
    for (const k of ['explainer_html', 'motion_reel', 'music_video']) {
      expect(w.find(`[data-testid="kind-card-${k}"]`).exists()).toBe(true)
    }
    expect(w.find('[data-testid="kind-card-explainer_manim"]').exists()).toBe(false)
    expect(w.get('[data-testid="kind-card-explainer_html"]').attributes('disabled')).toBeUndefined()
    const reel = w.get('[data-testid="kind-card-motion_reel"]')
    expect(reel.attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="kind-reason-motion_reel"]').text()).toContain('尚未实现')
  })

  it('音乐视频卡片可选：配置为无旁白的 HTML 加导入音乐，流水线是两个阶段', () => {
    w = mountPicker('music_video', 'import')
    const card = w.get('[data-testid="kind-card-music_video"]')
    expect(card.attributes('disabled')).toBeUndefined()
    expect(w.find('[data-testid="kind-reason-music_video"]').exists()).toBe(false)
    expect(w.get('[data-testid="kind-pipeline"]').text()).toContain('创意与要求 → 配乐与动画')
  })

  it('当前是 HTML 讲解时有配乐下拉，合成和导入禁用', () => {
    w = mountPicker()
    const options = w.findAll('[data-testid="music-select"] option')
    expect(options.map((o) => o.attributes('value'))).toEqual(['none', 'synth', 'import'])
    expect(options[0].attributes('disabled')).toBeUndefined()
    expect(options[1].attributes('disabled')).toBeDefined()
    expect(options[2].attributes('disabled')).toBeDefined()
    expect(options[1].text()).toContain('尚未实现')
  })

  it('显示所选配置的流水线', () => {
    w = mountPicker()
    expect(w.get('[data-testid="kind-pipeline"]').text()).toContain('选题 → 叙事 → 动画')
  })

  it('只有一个配乐选择的预设不显示配乐下拉', () => {
    w = mountPicker('motion_reel', 'synth')
    expect(w.find('[data-testid="music-select"]').exists()).toBe(false)
  })

  it('两种模式都给时分成「分阶段」与「自由」两组', () => {
    w = mountPicker()
    expect(w.get('[data-testid="kind-group-staged"]').text()).toContain('分阶段')
    expect(w.get('[data-testid="kind-group-free"]').text()).toContain('自由')
    expect(w.find('[data-testid="kind-card-free-explainer_html"]').exists()).toBe(true)
  })

  it('选自由讲解：配乐只有无配乐与合成，流水线是单个「自由讲解」阶段', async () => {
    w = mountPicker()
    await w.get('[data-testid="kind-card-free-explainer_html"]').trigger('click')
    expect(w.props('preset')).toBe('free-explainer_html')
    const options = w.findAll('[data-testid="music-select"] option')
    expect(options.map((o) => o.attributes('value'))).toEqual(['none', 'synth'])
    expect(w.get('[data-testid="kind-pipeline"]').text()).toContain('自由讲解')
  })

  it('只给自由模式时只有三张自由卡片，不分组', () => {
    w = mountPicker('free-motion_reel', 'synth', ['free'])
    const cards = w.findAll('[data-testid^="kind-card-"]')
    expect(cards.map((c) => c.attributes('data-testid'))).toEqual([
      'kind-card-free-explainer_html',
      'kind-card-free-motion_reel',
      'kind-card-free-music_video',
    ])
    expect(w.find('[data-testid="kind-group-staged"]').exists()).toBe(false)
    expect(w.find('[data-testid="kind-group-free"]').exists()).toBe(false)
  })
})
