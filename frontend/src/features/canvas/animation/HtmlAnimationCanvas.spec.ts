import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/http'
import type { HtmlPreviewMeta } from '@/types/api'

const META: HtmlPreviewMeta = {
  hash: 'h1',
  duration: 3,
  sections: [
    { id: 's-hook', label: '开场', start: 0, end: 1.4, beats: [] },
    { id: 's-explain', label: '讲解', start: 1.4, end: 3, beats: [] },
  ],
  audio: [],
  music: null,
}

const state = vi.hoisted(() => ({
  meta: undefined as unknown,
  metaError: undefined as unknown,
  project: undefined as unknown,
  files: [] as string[],
  written: [] as Array<{ path: string; stage: string; content: string }>,
}))

vi.mock('@/composables/queries', async () => {
  const { ref: vueRef, computed } = await import('vue')
  return {
    useHtmlPreviewMetaQuery: () => ({ data: vueRef(state.meta), error: vueRef(state.metaError) }),
    useProjectQuery: () => ({ data: vueRef(state.project) }),
    useFileTreeQuery: () => ({ data: vueRef({ files: state.files.map((path) => ({ path })) }) }),
    useFileContentQuery: (_id: unknown, path: () => string | null) => ({
      data: computed(() => (path() === null ? undefined : 'module.exports = {}\n')),
    }),
    useSceneChecksQuery: () => ({ data: vueRef(undefined) }),
    useWriteFileMutation: () => ({
      isPending: vueRef(false),
      mutateAsync: (input: { path: string; stage: string; content: string }) => {
        state.written.push(input)
        return Promise.resolve()
      },
    }),
  }
})
vi.mock('@/components/CodeEditor.vue', () => ({
  default: {
    name: 'CodeEditor',
    props: ['content', 'language', 'readonly'],
    emits: ['update:content'],
    render() {
      return h(
        'button',
        {
          'data-testid': 'code-editor',
          'data-language': this.language,
          onClick: () => this.$emit('update:content', 'edited();\n'),
        },
        this.content,
      )
    },
  },
}))

import HtmlAnimationCanvas from './HtmlAnimationCanvas.vue'

const previewMounts = { count: 0 }
const stubs = {
  // exposes the prop so the test can read it

  FinalRenderPanel: { props: ['sceneCount'], render() { return h('div', { 'data-testid': 'final-panel' }, `final ${this.sceneCount}`) } },
  HtmlPreviewPane: {
    props: ['scoreMissing', 'active'],
    created() {
      previewMounts.count += 1
    },
    render() {
      return h('div', {
        'data-testid': 'preview-pane',
        'data-score-missing': String(this.scoreMissing),
        'data-active': String(this.active),
      })
    },
  },
}
const mountCanvas = (busy = false) =>
  mount(HtmlAnimationCanvas, { props: { projectId: 'p1', busy }, global: { stubs } })

describe('HtmlAnimationCanvas', () => {
  beforeEach(() => {
    state.meta = META
    state.metaError = undefined
    state.project = undefined
    state.files = ['animation/scenes/s-hook.js']
    state.written = []
    previewMounts.count = 0
  })

  it('has three tabs and counts scenes from the preview meta', () => {
    const wrapper = mountCanvas()
    const tabs = wrapper.find('[data-testid="animation-tabbar"]').text()
    expect(tabs).toContain('镜头（2）')
    expect(tabs).toContain('实时预览')
    expect(tabs).toContain('成片')
  })

  it('lists scenes from the meta even before upstream is materialised', () => {
    const wrapper = mountCanvas()
    expect(wrapper.text()).toContain('s-hook')
    expect(wrapper.text()).toContain('s-explain')
  })

  it('shows the live preview only on its tab', async () => {
    const wrapper = mountCanvas()
    expect(wrapper.find('[data-testid="preview-pane"]').exists()).toBe(false)
    await wrapper.findAll('button').find((b) => b.text() === '实时预览')!.trigger('click')
    expect(wrapper.find('[data-testid="preview-pane"]').exists()).toBe(true)
  })

  it('keeps the preview mounted (hidden, told it is inactive) when switching to another tab', async () => {
    // TD-70: remounting would refetch the whole self-contained page (fonts included) every time.
    const wrapper = mountCanvas()
    const tab = (name: string) => wrapper.findAll('button').find((b) => b.text().startsWith(name))!
    await tab('实时预览').trigger('click')
    expect(previewMounts.count).toBe(1)
    expect(wrapper.get('[data-testid="preview-pane"]').attributes('data-active')).toBe('true')

    await tab('镜头').trigger('click')
    const hidden = wrapper.get('[data-testid="preview-pane"]')
    expect(hidden.attributes('data-active')).toBe('false')
    expect((hidden.element as HTMLElement).style.display).toBe('none')

    await tab('实时预览').trigger('click')
    expect(previewMounts.count).toBe(1)
    expect((wrapper.get('[data-testid="preview-pane"]').element as HTMLElement).style.display).not.toBe('none')
  })

  it('passes the scene count to the final render panel', () => {
    expect(mountCanvas().find('[data-testid="final-panel"]').text()).toBe('final 2')
  })

  it('opens a scene in the javascript editor and saves it under the animation_html stage', async () => {
    const wrapper = mountCanvas()
    await wrapper.findAll('li button')[0]!.trigger('click')
    await flushPromises()
    const editor = wrapper.find('[data-testid="code-editor"]')
    expect(editor.attributes('data-language')).toBe('javascript')
    await editor.trigger('click') // the stub emits an edit
    await wrapper.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(state.written).toEqual([
      { path: 'animation/scenes/s-hook.js', stage: 'animation_html', content: 'edited();\n' },
    ])
  })

  it('makes the editor read-only while an agent turn is running', async () => {
    const wrapper = mountCanvas(true)
    await wrapper.findAll('li button')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('只读：agent 正在运行')
  })

  it('shows why the timeline is unavailable instead of an empty canvas', () => {
    state.meta = undefined
    state.metaError = new ApiError(409, 'narrative/timing.json 不存在')
    const wrapper = mountCanvas()
    expect(wrapper.find('[data-testid="meta-problem"]').text()).toContain('narrative/timing.json')
    expect(wrapper.find('[data-testid="animation-tabbar"]').text()).toContain('镜头（0）')
  })

  it('tells the preview the score is missing only for a synth-music project without one', async () => {
    const tabOf = async (project: unknown, meta: unknown) => {
      state.project = project
      state.meta = meta
      const wrapper = mountCanvas()
      await wrapper.findAll('button').find((b) => b.text() === '实时预览')!.trigger('click')
      return wrapper.find('[data-testid="preview-pane"]').attributes('data-score-missing')
    }
    const synth = { kind: { music_source: 'synth' } }
    expect(await tabOf(synth, META)).toBe('true')
    expect(await tabOf(synth, { ...META, music: { url: '/m', gain: 1 } })).toBe('false')
    expect(await tabOf({ kind: { music_source: 'none' } }, META)).toBe('false')
    expect(await tabOf(undefined, META)).toBe('false')
  })

  it('also tells it for a song project (music_source import) whose song is not usable', async () => {
    state.project = { kind: { music_source: 'import' } }
    state.meta = META
    const wrapper = mountCanvas()
    await wrapper.findAll('button').find((b) => b.text() === '实时预览')!.trigger('click')
    expect(wrapper.find('[data-testid="preview-pane"]').attributes('data-score-missing')).toBe(
      'true',
    )
  })

  describe('produce stage (reel, music video)', () => {
    const mountProduce = (withMusicSlot = true) =>
      mount(HtmlAnimationCanvas, {
        props: { projectId: 'p1', busy: false, stage: 'produce' },
        slots: withMusicSlot
          ? { music: () => h('div', { 'data-testid': 'music-slot' }, '配乐内容') }
          : {},
        global: { stubs },
      })

    it('开工前（还没有镜头划分、配乐）是中性提示，不是红色错误，也没有重复的「时间轴不可用」前缀', () => {
      state.meta = undefined
      state.metaError = new ApiError(
        409,
        '时间轴不可用，共 1 个问题：\n- animation/shots.json 不存在（在 animation/shots.json 里写镜头划分）',
      )
      const wrapper = mountProduce()
      expect(wrapper.find('[data-testid="meta-problem"]').exists()).toBe(false)
      const hint = wrapper.find('[data-testid="produce-not-started"]')
      expect(hint.text()).toContain('还没有开始')
      expect(hint.text()).toContain('animation/shots.json')
      expect(hint.attributes('role')).toBeUndefined() // not an alert
    })

    it('真正的错误（文件存在但不合法）仍是红色，且前缀不重复', () => {
      state.meta = undefined
      state.metaError = new ApiError(
        409,
        '时间轴不可用，共 1 个问题：\n- animation/shots.json：镜头 a 与 b 之间有缝隙',
      )
      const wrapper = mountProduce()
      expect(wrapper.find('[data-testid="produce-not-started"]').exists()).toBe(false)
      const text = wrapper.find('[data-testid="meta-problem"]').text()
      expect(text).toContain('有缝隙')
      expect(text.match(/时间轴不可用/g)).toHaveLength(1)
    })

    it('adds a 配乐 tab that shows the music slot, next to 镜头 / 实时预览 / 成片', async () => {
      const wrapper = mountProduce()
      const tabs = wrapper.find('[data-testid="animation-tabbar"]').text()
      expect(tabs).toContain('镜头（2）')
      expect(tabs).toContain('实时预览')
      expect(tabs).toContain('配乐')
      expect(tabs).toContain('成片')
      const panel = () => wrapper.find('[data-testid="music-panel"]')
      expect(panel().attributes('style') ?? '').toContain('display: none')
      await wrapper.find('[data-testid="tab-music"]').trigger('click')
      expect(panel().attributes('style') ?? '').not.toContain('display: none')
      expect(wrapper.find('[data-testid="music-slot"]').text()).toBe('配乐内容')
    })

    it('has no 配乐 tab without a music slot, and not for the explainer stage', () => {
      expect(mountProduce(false).find('[data-testid="tab-music"]').exists()).toBe(false)
      expect(mountCanvas().find('[data-testid="tab-music"]').exists()).toBe(false)
    })

    it('saves scene code under the produce stage', async () => {
      const wrapper = mountProduce()
      await wrapper.findAll('li button')[0]!.trigger('click')
      await flushPromises()
      await wrapper.find('[data-testid="code-editor"]').trigger('click')
      await wrapper.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
      await flushPromises()
      expect(state.written).toEqual([
        { path: 'animation/scenes/s-hook.js', stage: 'produce', content: 'edited();\n' },
      ])
    })
  })
})
