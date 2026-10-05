import { mount } from '@vue/test-utils'
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { ApiError } from '@/api/http'
import type { MusicMetaOut } from '@/types/api'

const state = vi.hoisted(() => ({ meta: undefined as unknown, metaError: undefined as unknown }))

vi.mock('@/composables/queries', async () => {
  const { ref } = await import('vue')
  return {
    useMusicMetaQuery: () => ({ data: ref(state.meta), error: ref(state.metaError) }),
    useUploadMusicSourceMutation: () => ({ mutateAsync: () => Promise.resolve({}) }),
  }
})

import ImportMusicCanvas from './ImportMusicCanvas.vue'

const UPLOADED: MusicMetaOut = {
  form: 'import',
  rendered: true,
  stale: false,
  hash: 'abc',
  duration: null,
  bpm: null,
  events: [],
  sections: [],
  waveform: [],
  metrics: null,
  source: { filename: 'source.mp3', size: 100, sha256: 'abc', duration: null },
  analysis: null,
  grid: null,
  range: null,
  energy: null,
  sections_check: null,
}
const ANALYSED: MusicMetaOut = {
  ...UPLOADED,
  duration: 20,
  source: { ...UPLOADED.source!, duration: 20 },
  analysis: { bpm: 120, confidence: 0.9, residual_ms: 4, duration: 20, warnings: [] },
  grid: { bpm: 120, offset: 0.5, downbeats: [0.5, 2.5] },
  range: { start: 0.5, end: 18.5 },
  energy: { hop: 0.1, values: [0.1, 0.9, 0.5] },
  sections: [{ id: 'a', label: 'intro', start: 0.5, end: 18.5 }],
  sections_check: { ok: true, errors: [], warnings: [] },
}

const mountCanvas = (busy = false) => mount(ImportMusicCanvas, { props: { projectId: 'p1', busy } })
const has = (w: ReturnType<typeof mountCanvas>, id: string) => w.find(`[data-testid="${id}"]`).exists()

describe('ImportMusicCanvas', () => {
  beforeEach(() => {
    state.meta = undefined
    state.metaError = undefined
  })

  it('未上传：只有上传区，没有播放器与摘要', () => {
    state.meta = { ...UPLOADED, rendered: false, hash: null, source: null }
    const wrapper = mountCanvas()
    expect(has(wrapper, 'music-not-uploaded')).toBe(true)
    expect(has(wrapper, 'music-uploader')).toBe(true)
    expect(has(wrapper, 'music-audio')).toBe(false)
    expect(has(wrapper, 'music-analysis')).toBe(false)
  })

  it('已上传未分析：播放器、空的能量区提示、更换歌曲入口与“让 agent 分析”', () => {
    state.meta = UPLOADED
    const wrapper = mountCanvas()
    expect(wrapper.find('[data-testid="music-audio"]').attributes('src')).toBe(
      '/api/projects/p1/music/audio?v=abc',
    )
    expect(has(wrapper, 'music-no-energy')).toBe(true)
    expect(has(wrapper, 'energy-view')).toBe(false)
    expect(wrapper.find('[data-testid="music-upload-button"]').text()).toBe('更换歌曲')
    expect(has(wrapper, 'music-analysis-empty')).toBe(true)
  })

  it('已分析：能量曲线带叠加层，摘要与校验通过', () => {
    state.meta = ANALYSED
    const wrapper = mountCanvas()
    expect(has(wrapper, 'energy-view')).toBe(true)
    expect(has(wrapper, 'energy-mask-left')).toBe(true)
    expect(wrapper.findAll('[data-testid="energy-section"]')).toHaveLength(1)
    expect(has(wrapper, 'music-check-ok')).toBe(true)
  })

  it('校验有错与 stale 各自可见', () => {
    state.meta = { ...ANALYSED, sections_check: { ok: false, errors: ['x'], warnings: [] } }
    expect(has(mountCanvas(), 'music-check-error')).toBe(true)
    state.meta = { ...ANALYSED, stale: true }
    expect(has(mountCanvas(), 'music-stale')).toBe(true)
  })

  it('点击能量曲线更新播放器的 currentTime', async () => {
    state.meta = ANALYSED
    const wrapper = mount(ImportMusicCanvas, { props: { projectId: 'p1', busy: false }, attachTo: document.body })
    const audio = wrapper.find('[data-testid="music-audio"]').element as HTMLAudioElement
    const svg = wrapper.find('[data-testid="energy-svg"]')
    svg.element.getBoundingClientRect = () => ({ left: 0, width: 400 }) as DOMRect
    await svg.trigger('click', { clientX: 100 })
    expect(audio.currentTime).toBe(5)
    wrapper.unmount()
  })

  it('接口出错时显示原因；busy 时上传区被禁用', () => {
    state.meta = undefined
    state.metaError = new ApiError(404, '这个项目没有配乐')
    expect(mountCanvas().find('[data-testid="music-problem"]').text()).toBe('这个项目没有配乐')
    state.metaError = undefined
    state.meta = UPLOADED
    expect(
      mountCanvas(true).find('[data-testid="music-upload-button"]').attributes('disabled'),
    ).toBeDefined()
  })

  it('上传成功的提示不随画布从上传区切到已上传分支而消失', async () => {
    state.meta = { ...UPLOADED, rendered: false, hash: null, source: null }
    const wrapper = mountCanvas()
    expect(has(wrapper, 'music-upload-note')).toBe(false)
    wrapper
      .findComponent({ name: 'SourceUploader' })
      .vm.$emit('uploaded', { filename: 'source.mp3', size: 1, sha256: 'x', duration: 10 })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="music-upload-note"]').text()).toContain('analyze_music')
  })

  it('actions 槽的内容显示出来', () => {
    state.meta = UPLOADED
    const wrapper = mount(ImportMusicCanvas, {
      props: { projectId: 'p1', busy: false },
      slots: { actions: '<button data-testid="slot-action">定稿</button>' },
    })
    expect(has(wrapper, 'slot-action')).toBe(true)
  })
})
