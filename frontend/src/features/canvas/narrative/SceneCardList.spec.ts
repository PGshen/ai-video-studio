import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SceneCardList from './SceneCardList.vue'
import type { NarrativeScene } from './narrativeDoc'

const scrollIntoView = vi.fn()

const scene = (id: string): NarrativeScene => ({ id, narration: `旁白 ${id}`, visual_intent: '', beats: [] })

const mountList = (playingId: string | null) =>
  mount(SceneCardList, {
    props: {
      scenes: [scene('a'), scene('b'), scene('c')],
      issues: {},
      dubbing: {},
      selectedId: null,
      playingId,
    },
    attachTo: document.body,
  })

describe('SceneCardList 整体播放', () => {
  beforeEach(() => {
    scrollIntoView.mockClear()
    Element.prototype.scrollIntoView = scrollIntoView
  })

  it('只有正在播放的镜头带 data-playing', () => {
    const w = mountList('b')
    const flags = w.findAll('li button').map((b) => b.attributes('data-playing'))
    expect(flags).toEqual([undefined, 'true', undefined])
  })

  it('没有在播放时没有任何高亮，也不滚动', () => {
    const w = mountList(null)
    expect(w.findAll('[data-playing]')).toHaveLength(0)
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('当前播放的镜头变化时滚动到它', async () => {
    const w = mountList('a')
    scrollIntoView.mockClear()
    await w.setProps({ playingId: 'c' })
    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    expect(scrollIntoView.mock.instances[0]).toBe(w.findAll('li button')[2]!.element)
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' })
  })

  it('挂载时已经在播放（切回镜头标签）也滚动到当前镜头', async () => {
    mountList('b')
    await nextTick()
    expect(scrollIntoView).toHaveBeenCalledTimes(1)
  })
})
