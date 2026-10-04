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
}

const state = vi.hoisted(() => ({
  meta: undefined as unknown,
  metaError: undefined as unknown,
  files: [] as string[],
  written: [] as Array<{ path: string; stage: string; content: string }>,
}))

vi.mock('@/composables/queries', async () => {
  const { ref: vueRef, computed } = await import('vue')
  return {
    useHtmlPreviewMetaQuery: () => ({ data: vueRef(state.meta), error: vueRef(state.metaError) }),
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

const stubs = {
  FinalRenderPanel: { props: ['sceneCount'], render() { return h('div', { 'data-testid': 'final-panel' }, `final ${this.sceneCount}`) } },
  HtmlPreviewPane: { render() { return h('div', { 'data-testid': 'preview-pane' }) } },
}
const mountCanvas = (busy = false) =>
  mount(HtmlAnimationCanvas, { props: { projectId: 'p1', busy }, global: { stubs } })

describe('HtmlAnimationCanvas', () => {
  beforeEach(() => {
    state.meta = META
    state.metaError = undefined
    state.files = ['animation/scenes/s-hook.js']
    state.written = []
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
})
