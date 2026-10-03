import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const NARRATIVE = JSON.stringify({
  scenes: ['a', 'b', 'c'].map((id) => ({
    id,
    narration: `旁白 ${id}`,
    visual_intent: '意图',
    beats: [{ cue_text: 'c', visual_action: 'v', emphasis: 'e', transition: 't' }],
  })),
})
const timing = (id: string) => ({
  id,
  audio_path: `narrative/audio/${id}.mp3`,
  audio_hash: 'h',
  duration_seconds: 1,
  beats: [{ start_seconds: 0, end_seconds: 1 }],
  alignment_coverage: 1,
})

const state = vi.hoisted(() => ({
  files: [] as string[],
  timing: undefined as string | undefined,
}))

vi.mock('@/composables/queries', async () => {
  const { ref: vueRef } = await import('vue')
  return {
    useFileTreeQuery: () => ({ data: vueRef({ files: state.files.map((path) => ({ path })) }) }),
    // 内容在挂载时就已就绪（查询缓存命中，例如从选题阶段切回叙事）：不会再有"变化"事件。
    useFileContentQuery: (_id: unknown, path: () => string | null) => ({
      data: vueRef(
        path() === 'narrative/narrative.json'
          ? NARRATIVE
          : path() === 'narrative/timing.json'
            ? state.timing
            : undefined,
      ),
    }),
    useProjectQuery: () => ({ data: vueRef({ settings: {} }) }),
    useWriteFileMutation: () => ({ isPending: vueRef(false), mutateAsync: () => Promise.resolve() }),
  }
})
vi.mock('@/components/CodeEditor.vue', () => ({
  default: { name: 'CodeEditor', render: () => h('div', { 'data-testid': 'code-editor' }) },
}))

import NarrativeCanvas from './NarrativeCanvas.vue'

class FakeAudio {
  static instances: FakeAudio[] = []
  src = ''
  private ended: Array<() => void> = []
  constructor() {
    FakeAudio.instances.push(this)
  }
  addEventListener(type: string, fn: () => void): void {
    if (type === 'ended') this.ended.push(fn)
  }
  removeEventListener(): void {}
  play(): Promise<void> {
    return Promise.resolve()
  }
  pause(): void {}
  finish(): void {
    this.ended.forEach((fn) => fn())
  }
}

const mountCanvas = () => mount(NarrativeCanvas, { props: { projectId: 'p1', busy: false } })

describe('NarrativeCanvas', () => {
  beforeEach(() => {
    state.files = ['narrative/narrative.json']
    state.timing = undefined
  })

  it('narrative.json 已在缓存里时，切到原始 JSON 标签直接显示编辑器而不是一直"加载中"', async () => {
    const w = mountCanvas()
    await w.findAll('button').find((b) => b.text() === '原始 JSON')!.trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('加载中')
    expect(w.find('[data-testid="code-editor"]').exists()).toBe(true)
  })

  it('还有镜头没配音：「播放」不可用', () => {
    state.files.push('narrative/timing.json', 'narrative/audio/a.mp3')
    state.timing = JSON.stringify({ scenes: [timing('a')] })
    const w = mountCanvas()
    expect(w.get('[data-testid="play-all"]').attributes('disabled')).toBeDefined()
  })

  it('每个镜头都有配音文件：「播放」可用，与状态图标同在标签行', () => {
    state.files.push('narrative/timing.json', 'narrative/audio/a.mp3', 'narrative/audio/b.mp3', 'narrative/audio/c.mp3')
    state.timing = JSON.stringify({ scenes: [timing('a'), timing('b'), timing('c')] })
    const w = mountCanvas()
    const button = w.get('[data-testid="play-all"]')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(button.text()).toContain('播放')
    expect(w.get('[data-testid="narrative-tabbar"]').find('[data-testid="readiness"]').exists()).toBe(true)
  })

  describe('整体播放', () => {
    beforeEach(() => {
      FakeAudio.instances = []
      vi.stubGlobal('Audio', FakeAudio)
      Element.prototype.scrollIntoView = vi.fn() // jsdom 没有
      state.files.push(
        'narrative/timing.json',
        'narrative/audio/a.mp3',
        'narrative/audio/b.mp3',
        'narrative/audio/c.mp3',
      )
      state.timing = JSON.stringify({ scenes: [timing('a'), timing('b'), timing('c')] })
    })
    afterEach(() => vi.unstubAllGlobals())

    const card = (w: ReturnType<typeof mountCanvas>, id: string) =>
      w.findAll('li button').find((b) => b.text().startsWith(id))!
    const detail = (w: ReturnType<typeof mountCanvas>) => w.text()
    const audio = () => FakeAudio.instances[0]!

    it('从选中的镜头开始往后播，右侧详情和选中态跟着当前镜头走', async () => {
      const w = mountCanvas()
      await card(w, 'b').trigger('click')
      await w.get('[data-testid="play-all"]').trigger('click')
      await flushPromises()
      expect(audio().src).toContain('b.mp3')
      expect(card(w, 'b').classes()).toContain('border-primary')

      audio().finish()
      await flushPromises()
      expect(audio().src).toContain('c.mp3')
      expect(detail(w)).toContain('旁白 c')
      expect(card(w, 'c').classes()).toContain('border-primary')
      expect(card(w, 'b').classes()).not.toContain('border-primary')
    })

    it('没有选中镜头时从第一个开始', async () => {
      const w = mountCanvas()
      await w.get('[data-testid="play-all"]').trigger('click')
      await flushPromises()
      expect(audio().src).toContain('a.mp3')
      expect(detail(w)).toContain('旁白 a')
    })

    it('播放中点另一个镜头：跳到该镜头继续往后播', async () => {
      const w = mountCanvas()
      await w.get('[data-testid="play-all"]').trigger('click')
      await flushPromises()
      await card(w, 'c').trigger('click')
      await flushPromises()
      expect(audio().src).toContain('c.mp3')
      expect(detail(w)).toContain('旁白 c')
    })

    it('暂停后点别的镜头只是选中，再点播放从它开始', async () => {
      const w = mountCanvas()
      await w.get('[data-testid="play-all"]').trigger('click')
      await flushPromises()
      await w.get('[data-testid="play-all"]').trigger('click') // 暂停在 a
      await card(w, 'c').trigger('click')
      await flushPromises()
      expect(audio().src).toContain('a.mp3')
      await w.get('[data-testid="play-all"]').trigger('click')
      await flushPromises()
      expect(audio().src).toContain('c.mp3')
    })
  })
})
