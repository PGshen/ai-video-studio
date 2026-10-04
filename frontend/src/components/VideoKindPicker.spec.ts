import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { VIDEO_KINDS_FIXTURE } from '@/test/videoKindsFixture'
import VideoKindPicker from './VideoKindPicker.vue'

function mountPicker(videoKind = 'explainer_manim', music = 'none') {
  return mount(VideoKindPicker, {
    props: {
      data: VIDEO_KINDS_FIXTURE,
      videoKind: videoKind as 'explainer_manim',
      music: music as 'none',
      'onUpdate:videoKind': (v: string) => w.setProps({ videoKind: v as 'explainer_manim' }),
      'onUpdate:music': (v: string) => w.setProps({ music: v as 'none' }),
    },
  })
}
let w: ReturnType<typeof mountPicker>

describe('VideoKindPicker', () => {
  it('渲染四张预设卡片，不可用的禁用并显示原因', () => {
    w = mountPicker()
    for (const k of ['explainer_manim', 'explainer_html', 'motion_reel', 'music_video']) {
      expect(w.find(`[data-testid="kind-card-${k}"]`).exists()).toBe(true)
    }
    expect(w.get('[data-testid="kind-card-explainer_manim"]').attributes('disabled')).toBeUndefined()
    const reel = w.get('[data-testid="kind-card-motion_reel"]')
    expect(reel.attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="kind-reason-motion_reel"]').text()).toContain('尚未实现')
  })

  it('当前是 Manim 讲解时有配乐下拉，合成和导入禁用', () => {
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
})
