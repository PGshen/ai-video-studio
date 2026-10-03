import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import KeyframeStrip from './KeyframeStrip.vue'

function strip(props: { images: string[]; stale?: boolean }) {
  return mount(KeyframeStrip, {
    props: { projectId: 'p1', sceneId: 's-hook', stale: false, ...props },
  })
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
})
