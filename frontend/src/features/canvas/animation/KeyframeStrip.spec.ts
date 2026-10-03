import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import KeyframeStrip from './KeyframeStrip.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

function strip(props: { images: string[]; stale?: boolean }) {
  return mount(KeyframeStrip, {
    props: { projectId: 'p1', sceneId: 's-hook', stale: false, ...props },
    attachTo: document.body,
  })
}

function dialogImageSrc(): string | null | undefined {
  return document.body.querySelector('[role="dialog"] img')?.getAttribute('src')
}

function dialogButton(label: string): HTMLButtonElement {
  const button = document.body.querySelector<HTMLButtonElement>(`[role="dialog"] [aria-label="${label}"]`)
  if (!button) throw new Error(`没有找到按钮：${label}`)
  return button
}

describe('KeyframeStrip', () => {
  it('有关键帧时按顺序渲染 blob 缩略图', () => {
    const wrapper = strip({ images: ['aaa', 'bbb'] })
    const srcs = wrapper.findAll('img').map((img) => img.attributes('src'))
    expect(srcs).toEqual(['/api/projects/p1/blobs/aaa', '/api/projects/p1/blobs/bbb'])
    expect(wrapper.text()).not.toContain('已过期')
  })

  it('代码在预览后改过时提示可能已过期', () => {
    const wrapper = strip({ images: ['aaa'], stale: true })
    expect(wrapper.text()).toContain('可能已过期')
  })

  it('没有关键帧时退回文字提示', () => {
    const wrapper = strip({ images: [] })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('render_preview')
  })

  it('放大后可以前后切换相邻关键帧，到头尾按钮禁用', async () => {
    const wrapper = strip({ images: ['aaa', 'bbb', 'ccc'] })
    await wrapper.findAll('button')[1]!.trigger('click')
    await flushPromises()
    expect(dialogImageSrc()).toBe('/api/projects/p1/blobs/bbb')

    dialogButton('下一张').click()
    await flushPromises()
    expect(dialogImageSrc()).toBe('/api/projects/p1/blobs/ccc')
    expect(dialogButton('下一张').disabled).toBe(true)

    dialogButton('上一张').click()
    dialogButton('上一张').click()
    await flushPromises()
    expect(dialogImageSrc()).toBe('/api/projects/p1/blobs/aaa')
    expect(dialogButton('上一张').disabled).toBe(true)
  })

  it('方向键切换关键帧', async () => {
    const wrapper = strip({ images: ['aaa', 'bbb'] })
    await wrapper.findAll('button')[0]!.trigger('click')
    await flushPromises()

    // 焦点不在弹窗里（例如掉到 body）时方向键也要生效。
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await flushPromises()
    expect(dialogImageSrc()).toBe('/api/projects/p1/blobs/bbb')

    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
    await flushPromises()
    expect(dialogImageSrc()).toBe('/api/projects/p1/blobs/aaa')
  })
})
