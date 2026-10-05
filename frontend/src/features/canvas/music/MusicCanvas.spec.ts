import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/http'
import type { MusicMetaOut, MusicRenderOut } from '@/types/api'

const META: MusicMetaOut = {
  rendered: true,
  stale: false,
  hash: 'abc',
  duration: 10,
  bpm: 128,
  events: [{ name: 'kick', kind: 'onset', start: 1, end: 1.2 }],
  sections: [{ id: 's1', label: 'BUILD', start: 0, end: 10 }],
  waveform: [0.1, 0.9],
  metrics: { peak_dbfs: -1, onsets: 5 },
}
const REPORT: MusicRenderOut = {
  ok: true,
  errors: [],
  text: 't',
  warnings: [],
  retime_note: '重定时校验通过',
  metrics: { peak_dbfs: -2 },
  picture_base64: null,
  picture_media_type: null,
}

const state = vi.hoisted(() => ({
  meta: undefined as unknown,
  metaError: undefined as unknown,
  files: [] as string[],
  content: 'import numpy\n',
  written: [] as Array<{ path: string; stage: string; content: string }>,
  rendered: 0,
  renderResult: undefined as unknown,
  renderError: undefined as unknown,
  pending: false,
}))

vi.mock('@/composables/queries', async () => {
  const { ref: vueRef, computed } = await import('vue')
  return {
    useMusicMetaQuery: () => ({ data: vueRef(state.meta), error: vueRef(state.metaError) }),
    useFileTreeQuery: () => ({ data: vueRef({ files: state.files.map((path) => ({ path })) }) }),
    useFileContentQuery: (_id: unknown, path: () => string | null) => ({
      data: computed(() => (path() === null ? undefined : state.content)),
    }),
    useWriteFileMutation: () => ({
      isPending: vueRef(false),
      mutateAsync: (input: { path: string; stage: string; content: string }) => {
        state.written.push(input)
        return Promise.resolve()
      },
    }),
    useRenderMusicMutation: () => ({
      isPending: vueRef(state.pending),
      mutateAsync: () => {
        state.rendered += 1
        return state.renderError ? Promise.reject(state.renderError) : Promise.resolve(state.renderResult)
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
          'data-readonly': String(this.readonly),
          onClick: () => this.$emit('update:content', 'edited()\n'),
        },
        this.content,
      )
    },
  },
}))

import MusicCanvas from './MusicCanvas.vue'

const seeks: number[] = []
const stubs = {
  MusicPlayer: {
    setup(_: unknown, { expose }: { expose: (api: object) => void }) {
      expose({ seek: (t: number) => seeks.push(t) })
      return () => h('div', { 'data-testid': 'player-stub' })
    },
  },
}
const mountCanvas = (busy = false) =>
  mount(MusicCanvas, { props: { projectId: 'p1', busy }, global: { stubs } })

describe('MusicCanvas', () => {
  beforeEach(() => {
    state.meta = META
    state.metaError = undefined
    state.files = ['music/compose.py']
    state.content = 'import numpy\n'
    state.written = []
    state.rendered = 0
    state.renderResult = REPORT
    state.renderError = undefined
    state.pending = false
    seeks.length = 0
  })

  it('has play / script / events tabs and counts the events', () => {
    const text = mountCanvas().find('[data-testid="music-tabbar"]').text()
    expect(text).toContain('播放')
    expect(text).toContain('脚本')
    expect(text).toContain('事件（1）')
  })

  it('shows the player for a rendered score and an empty state otherwise', () => {
    expect(mountCanvas().find('[data-testid="player-stub"]').exists()).toBe(true)
    state.meta = { ...META, rendered: false, events: [], waveform: [] }
    const wrapper = mountCanvas()
    expect(wrapper.find('[data-testid="music-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="player-stub"]').exists()).toBe(false)
  })

  it('warns when the score is stale and shows a project problem', () => {
    state.meta = { ...META, stale: true }
    expect(mountCanvas().find('[data-testid="music-stale"]').exists()).toBe(true)
    state.meta = undefined
    state.metaError = new ApiError(404, '这个项目没有合成配乐', '这个项目没有合成配乐')
    expect(mountCanvas().find('[data-testid="music-problem"]').text()).toContain('没有合成配乐')
  })

  it('edits the script as python and saves it into the music stage', async () => {
    const wrapper = mountCanvas()
    const editor = wrapper.find('[data-testid="code-editor"]')
    expect(editor.attributes('data-language')).toBe('python')
    await editor.trigger('click')
    await wrapper.find('[data-testid="music-save"]').trigger('click')
    await flushPromises()
    expect(state.written).toEqual([{ path: 'music/compose.py', stage: 'music', content: 'edited()\n' }])
  })

  it('renders without a turn, then shows the report', async () => {
    const wrapper = mountCanvas()
    await wrapper.find('[data-testid="music-render"]').trigger('click')
    await flushPromises()
    expect(state.rendered).toBe(1)
    expect(wrapper.find('[data-testid="render-report"]').text()).toContain('渲染成功')
  })

  it('shows a failed report and an HTTP problem separately', async () => {
    state.renderResult = { ...REPORT, ok: false, errors: ['脚本崩了'] }
    const wrapper = mountCanvas()
    await wrapper.find('[data-testid="music-render"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="render-errors"]').text()).toContain('脚本崩了')

    state.renderError = new ApiError(409, '当前平台没有沙箱', '当前平台没有沙箱')
    const other = mountCanvas()
    await other.find('[data-testid="music-render"]').trigger('click')
    await flushPromises()
    expect(other.find('[data-testid="music-render-error"]').text()).toContain('没有沙箱')
  })

  it('will not render while a turn runs, while unsaved, or without a script', async () => {
    const busy = mountCanvas(true)
    expect(busy.find('[data-testid="music-render"]').attributes('disabled')).toBeDefined()
    expect(busy.find('[data-testid="music-render-hint"]').text()).toContain('agent')
    expect(busy.find('[data-testid="code-editor"]').attributes('data-readonly')).toBe('true')

    const dirty = mountCanvas()
    await dirty.find('[data-testid="code-editor"]').trigger('click')
    expect(dirty.find('[data-testid="music-render"]').attributes('disabled')).toBeDefined()
    expect(dirty.find('[data-testid="music-render-hint"]').text()).toContain('保存')

    state.files = []
    const none = mountCanvas()
    expect(none.find('[data-testid="music-render"]').attributes('disabled')).toBeDefined()
    expect(state.rendered).toBe(0)
  })

  it('disables the button and says so while a render is running', () => {
    state.pending = true
    const wrapper = mountCanvas()
    const button = wrapper.find('[data-testid="music-render"]')
    expect(button.text()).toBe('渲染中…')
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('jumps back to the play tab when an event row is clicked', async () => {
    const wrapper = mountCanvas()
    await wrapper.find('[data-testid="music-tab-events"]').trigger('click')
    await wrapper.find('[data-testid="event-row"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="music-tab-play"]').classes()).toContain('text-primary')
    expect(seeks).toEqual([1])
  })
})
