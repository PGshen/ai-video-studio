import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SceneReference from './SceneReference.vue'
import type { NarrativeSceneInfo } from './narrativeScenes'

const SCENE: NarrativeSceneInfo = {
  id: 's-hook',
  narration: '这是旁白',
  visualIntent: '这是意图',
  beats: [
    { cueText: '第一句', visualAction: '数字滑入', emphasis: '强调规模', transition: 'reveal' },
    { cueText: '第二句', visualAction: '', emphasis: '', transition: '' },
  ],
}

function reference(tab: 'preview' | 'beats', narrativeScene: NarrativeSceneInfo | null = SCENE) {
  return mount(SceneReference, {
    props: {
      tab,
      'onUpdate:tab': (value: 'preview' | 'beats') => wrapper.setProps({ tab: value }),
      projectId: 'p1',
      sceneId: 's-hook',
      images: ['aaa', 'bbb'],
      stale: false,
      narrativeScene,
    },
  })
}

let wrapper: ReturnType<typeof reference>

describe('SceneReference', () => {
  it('预览标签显示关键帧，标签上带数量', () => {
    wrapper = reference('preview')
    expect(wrapper.findAll('img')).toHaveLength(2)
    expect(wrapper.find('[data-testid="scene-beats"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('预览（2）')
    expect(wrapper.text()).toContain('镜头 Beats（2）')
  })

  it('点“镜头 Beats”切换，显示旁白、意图和每个 beat', async () => {
    wrapper = reference('preview')
    const beatsTab = wrapper.findAll('[role="tab"]')[1]!
    await beatsTab.trigger('click')

    const text = wrapper.find('[data-testid="scene-beats"]').text()
    expect(text).toContain('这是旁白')
    expect(text).toContain('这是意图')
    expect(text).toContain('1. 第一句')
    expect(text).toContain('画面：数字滑入')
    expect(text).toContain('重点：强调规模')
    expect(text).toContain('2. 第二句')
    expect(wrapper.findAll('img')).toHaveLength(0)
  })

  it('叙事里找不到该镜头时给出提示', () => {
    wrapper = reference('beats', null)
    expect(wrapper.text()).toContain('没有找到这个镜头')
  })
})
