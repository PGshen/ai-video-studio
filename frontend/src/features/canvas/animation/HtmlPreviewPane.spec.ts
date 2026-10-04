import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HtmlPreviewMeta } from '@/types/api'
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
}

const mounted: Array<ReturnType<typeof mount>> = []
function mountPane(meta: HtmlPreviewMeta = META) {
  const wrapper = mount(HtmlPreviewPane, {
    props: { projectId: 'p1', meta },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  return wrapper
}
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount())
})

function frameWindow(wrapper: ReturnType<typeof mountPane>): Window {
  const frame = wrapper.find('iframe').element as HTMLIFrameElement
  return frame.contentWindow as Window
}

function fromWindow(source: Window | null, data: unknown): void {
  window.dispatchEvent(new MessageEvent('message', { data, source }))
}

describe('HtmlPreviewPane', () => {
  it('runs the page in a sandbox without same-origin access and keys the url by the hash', () => {
    const iframe = mountPane().find('iframe')
    expect(iframe.attributes('sandbox')).toBe('allow-scripts')
    expect(iframe.attributes('src')).toBe(
      '/api/projects/p1/animation/html-preview/?v=hash-1',
    )
  })

  it('sends the current time to the page once it reports ready', async () => {
    const wrapper = mountPane()
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    expect(post).toHaveBeenCalledWith({ type: 'seek', t: 0 }, '*')
  })

  it('shows the error banner for page errors and clears it when the page is ready again', async () => {
    const wrapper = mountPane()
    fromWindow(frameWindow(wrapper), { type: 'error', message: 'boom at lt=1' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="preview-error"]').text()).toContain('boom at lt=1')
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="preview-error"]').exists()).toBe(false)
  })

  it('ignores messages that do not come from its own iframe', async () => {
    const wrapper = mountPane()
    fromWindow(window, { type: 'error', message: 'spoofed' })
    fromWindow(null, { type: 'error', message: 'spoofed' })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="preview-error"]').exists()).toBe(false)
  })

  it('reloads the iframe only when the hash changes', async () => {
    const wrapper = mountPane()
    const first = wrapper.find('iframe').attributes('src')
    await wrapper.setProps({ meta: { ...META } })
    expect(wrapper.find('iframe').attributes('src')).toBe(first)
    await wrapper.setProps({ meta: { ...META, hash: 'hash-2' } })
    expect(wrapper.find('iframe').attributes('src')).toContain('v=hash-2')
  })

  it('seeks the page when the scrubber moves', async () => {
    const wrapper = mountPane()
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    const scrubber = wrapper.find('[data-testid="preview-scrubber"]')
    await scrubber.setValue('3.5')
    expect(post).toHaveBeenCalledWith({ type: 'seek', t: 3.5 }, '*')
    expect(wrapper.find('[data-testid="preview-time"]').text()).toContain('0:03.5')
  })

  it('draws a tick between each pair of sections and jumps to a section on click', async () => {
    const wrapper = mountPane()
    expect(wrapper.findAll('[data-testid="preview-tick"]')).toHaveLength(2)
    fromWindow(frameWindow(wrapper), { type: 'ready', duration: 6 })
    const post = vi.spyOn(frameWindow(wrapper), 'postMessage')
    await wrapper.findAll('[data-testid="preview-section"]')[2]!.trigger('click')
    expect(post).toHaveBeenCalledWith({ type: 'seek', t: 5 }, '*')
  })

  it('toggles the loop button', async () => {
    const wrapper = mountPane()
    const loop = wrapper.find('[data-testid="preview-loop"]')
    expect(loop.attributes('aria-pressed')).toBe('false')
    await loop.trigger('click')
    expect(loop.attributes('aria-pressed')).toBe('true')
  })
})
