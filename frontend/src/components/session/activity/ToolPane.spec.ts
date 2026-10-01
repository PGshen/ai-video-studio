import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ToolPane from './ToolPane.vue'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('ToolPane', () => {
  it('标题栏显示标题与语言，内容区限高可滚动', () => {
    const wrapper = mount(ToolPane, {
      props: { title: 'STYLE.md', language: 'md' },
      slots: { default: '<pre>正文</pre>' },
    })

    expect(wrapper.text()).toContain('STYLE.md')
    expect(wrapper.text()).toContain('md')
    expect(wrapper.text()).toContain('正文')
    expect(wrapper.get('[data-testid="tool-pane-body"]').classes()).toEqual(
      expect.arrayContaining(['max-h-80', 'overflow-auto']),
    )
  })

  it('没有 copyText 时不显示复制按钮', () => {
    const wrapper = mount(ToolPane, { props: { title: 't' } })

    expect(wrapper.find('[data-testid="tool-pane-copy"]').exists()).toBe(false)
  })

  it('点复制：把 copyText 写进剪贴板，按钮短暂变成「已复制」', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(ToolPane, { props: { title: 't', copyText: '要复制的内容' } })

    await wrapper.get('[data-testid="tool-pane-copy"]').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('要复制的内容')
    expect(wrapper.get('[data-testid="tool-pane-copy"]').text()).toBe('已复制')
    vi.advanceTimersByTime(1600)
    await flushPromises()
    expect(wrapper.get('[data-testid="tool-pane-copy"]').text()).toBe('复制')
  })

  it('剪贴板不可用时静默失败，按钮保持「复制」', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    const wrapper = mount(ToolPane, { props: { title: 't', copyText: 'x' } })

    await wrapper.get('[data-testid="tool-pane-copy"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="tool-pane-copy"]').text()).toBe('复制')
  })
})
