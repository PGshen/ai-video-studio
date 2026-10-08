import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HtmlPreviewMeta } from '@/types/api'

const api = vi.hoisted(() => ({ getHtmlPreviewPage: vi.fn() }))
vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  ...api,
}))

import HtmlPreviewPane from './HtmlPreviewPane.vue'

const META: HtmlPreviewMeta = {
  hash: 'hash-1',
  duration: 6,
  sections: [
    { id: 'a', label: '开场', start: 0, end: 2, beats: [] },
    { id: 'b', label: '讲解', start: 2, end: 5, beats: [] },
    { id: 'c', label: '收尾', start: 5, end: 6, beats: [] },
  ],
  audio: [],
  music: null,
}

const mounted: Array<ReturnType<typeof mount>> = []
async function mountPane(meta: HtmlPreviewMeta = META) {
  const wrapper = mount(HtmlPreviewPane, {
    props: { projectId: 'p1', meta },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  api.getHtmlPreviewPage.mockReset().mockResolvedValue('<!doctype html><p>page-1</p>')
})
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount())
})

function frameWindow(wrapper: Awaited<ReturnType<typeof mountPane>>): Window {
  const frame = wrapper.find('iframe').element as HTMLIFrameElement
  return frame.contentWindow as Window
}

function fromWindow(source: Window | null, data: unknown): void {
  window.dispatchEvent(new MessageEvent('message', { data, source }))
}

describe('HtmlPreviewPane', () => {
  it('runs the self-contained page in a sandbox without same-origin access', async () => {
    const iframe = (await mountPane()).find('iframe')
    expect(iframe.attributes('sandbox')).toBe('allow-scripts')
    expect(iframe.attributes('srcdoc')).toBe('<!doctype html><p>page-1</p>')
    expect(iframe.attributes('src')).toBeUndefined()
    expect(api.getHtmlPreviewPage).toHaveBeenCalledWith('p1')
  })

  it('says so when the page cannot be fetched', async () => {
    api.getHtmlPreviewPage.mockReset().mockRejectedValue(new Error('network down'))
    const wrapper = await mountPane()
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('[data-testid="preview-error"]').text()).toContain('network down')
  })

  it('sends the current time to the page once it reports ready', async () => {
    const wrapper = await mountPane()
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    expect(post).toHaveBeenCalledWith({ type: 'seek', t: 0 }, '*')
  })

  it('shows the error banner for page errors and clears it when the page is ready again', async () => {
    const wrapper = await mountPane()
    fromWindow(frameWindow(wrapper), { type: 'error', message: 'boom at lt=1' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="preview-error"]').text()).toContain('boom at lt=1')
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="preview-error"]').exists()).toBe(false)
  })

  it('ignores messages that do not come from its own iframe', async () => {
    const wrapper = await mountPane()
    fromWindow(window, { type: 'error', message: 'spoofed' })
    fromWindow(null, { type: 'error', message: 'spoofed' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="preview-error"]').exists()).toBe(false)
  })

  it('reloads the page only when the hash changes', async () => {
    const wrapper = await mountPane()
    await wrapper.setProps({ meta: { ...META } })
    await flushPromises()
    expect(api.getHtmlPreviewPage).toHaveBeenCalledTimes(1)
    api.getHtmlPreviewPage.mockResolvedValue('<!doctype html><p>page-2</p>')
    await wrapper.setProps({ meta: { ...META, hash: 'hash-2' } })
    await flushPromises()
    expect(api.getHtmlPreviewPage).toHaveBeenCalledTimes(2)
    expect(wrapper.find('iframe').attributes('srcdoc')).toBe('<!doctype html><p>page-2</p>')
  })

  it('keeps the newest page when an older fetch resolves late', async () => {
    let releaseFirst: (html: string) => void = () => {}
    api.getHtmlPreviewPage.mockReset()
    api.getHtmlPreviewPage
      .mockReturnValueOnce(new Promise<string>((resolve) => (releaseFirst = resolve)))
      .mockResolvedValueOnce('<p>newest</p>')
    const wrapper = mount(HtmlPreviewPane, {
      props: { projectId: 'p1', meta: META },
      attachTo: document.body,
    })
    mounted.push(wrapper)
    await wrapper.setProps({ meta: { ...META, hash: 'hash-2' } })
    await flushPromises()
    releaseFirst('<p>stale</p>')
    await flushPromises()
    expect(wrapper.find('iframe').attributes('srcdoc')).toBe('<p>newest</p>')
  })

  it('seeks the page when the scrubber moves', async () => {
    const wrapper = await mountPane()
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    const scrubber = wrapper.find('[data-testid="preview-scrubber"]')
    await scrubber.setValue('3.5')
    expect(post).toHaveBeenCalledWith({ type: 'seek', t: 3.5 }, '*')
    expect(wrapper.find('[data-testid="preview-time"]').text()).toContain('0:03.5')
  })

  it('never asks the page for the empty frame at exactly the end of the timeline', async () => {
    const wrapper = await mountPane()
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    await wrapper.find('[data-testid="preview-scrubber"]').setValue('6')
    const sent = post.mock.calls.at(-1)?.[0] as { t: number }
    expect(sent.t).toBeLessThan(6)
    expect(sent.t).toBeCloseTo(6 - 1 / 30)
  })

  it('draws a tick between each pair of sections and jumps to a section on click', async () => {
    const wrapper = await mountPane()
    expect(wrapper.findAll('[data-testid="preview-tick"]')).toHaveLength(2)
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    await wrapper.findAll('[data-testid="preview-section"]')[2]!.trigger('click')
    expect(post).toHaveBeenCalledWith({ type: 'seek', t: 5 }, '*')
  })

  it('pauses playback when it is no longer the active tab, and leaves it paused', async () => {
    const wrapper = await mountPane()
    const play = wrapper.find('[data-testid="preview-play"]')
    await play.trigger('click')
    expect(play.attributes('aria-label')).toBe('暂停')

    await wrapper.setProps({ active: false })
    expect(play.attributes('aria-label')).toBe('播放')
    await wrapper.setProps({ active: true })
    expect(play.attributes('aria-label')).toBe('播放')
  })

  it('toggles the loop button', async () => {
    const wrapper = await mountPane()
    const loop = wrapper.find('[data-testid="preview-loop"]')
    expect(loop.attributes('aria-pressed')).toBe('false')
    await loop.trigger('click')
    expect(loop.attributes('aria-pressed')).toBe('true')
  })

  it('offers a mute button only when there is a score, and toggles it', async () => {
    expect((await mountPane()).find('[data-testid="preview-mute"]').exists()).toBe(false)
    const wrapper = await mountPane({ ...META, music: { url: '/m.wav', gain: 1 } })
    const mute = wrapper.find('[data-testid="preview-mute"]')
    expect(mute.attributes('aria-pressed')).toBe('false')
    await mute.trigger('click')
    expect(mute.attributes('aria-pressed')).toBe('true')
  })

  it('says why there is no sound when the score is missing or stale', async () => {
    const wrapper = mount(HtmlPreviewPane, {
      props: { projectId: 'p1', meta: META, scoreMissing: true },
      attachTo: document.body,
    })
    mounted.push(wrapper)
    await flushPromises()
    expect(wrapper.find('[data-testid="preview-score-missing"]').text()).toContain('配乐')
    expect((await mountPane()).find('[data-testid="preview-score-missing"]').exists()).toBe(false)
  })
})
