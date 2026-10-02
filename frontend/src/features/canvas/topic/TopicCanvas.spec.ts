import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  files: [] as Array<{ path: string }>,
  check: undefined as unknown,
}))

vi.mock('@/composables/queries', async () => {
  const { ref: vueRef } = await import('vue')
  return {
    useFileTreeQuery: () => ({ data: vueRef({ files: state.files }) }),
    useTopicCheckQuery: () => ({ data: vueRef(state.check) }),
    useFileContentQuery: () => ({ data: vueRef('# hi'), isError: vueRef(false) }),
    useWriteFileMutation: () => ({ isPending: vueRef(false), mutateAsync: () => Promise.resolve() }),
  }
})
vi.mock('@/components/CodeEditor.vue', () => ({
  default: { name: 'CodeEditor', render: () => h('div', { 'data-testid': 'code-editor' }) },
}))
vi.mock('@/components/ai-elements/message/MessageResponse.vue', () => ({
  default: { name: 'MessageResponse', render: () => h('div', { 'data-testid': 'rendered' }) },
}))

import TopicCanvas from './TopicCanvas.vue'

const mountCanvas = (busy = false) =>
  mount(TopicCanvas, { props: { projectId: 'p1', busy }, attachTo: document.body })

describe('TopicCanvas', () => {
  beforeEach(() => {
    state.files = [{ path: 'topic/brief.md' }, { path: 'topic/notes/a.md' }, { path: 'topic/notes/b.md' }]
    state.check = { errors: [], warnings: [] }
    document.body.innerHTML = ''
  })

  it('不再有检查条；状态图标和渲染/编辑切换与标签在同一行', () => {
    const w = mountCanvas()
    expect(w.find('[data-testid="brief-check"]').exists()).toBe(false)
    const bar = w.get('[data-testid="topic-tabbar"]')
    expect(bar.text()).toContain('简报')
    expect(bar.text()).toContain('笔记（2）')
    expect(bar.find('[data-testid="brief-status"]').exists()).toBe(true)
    expect(bar.find('[data-testid="mode-edit"]').exists()).toBe(true)
  })

  it('文件内容区不再有自己的渲染/编辑切换条和「只读」提示行', () => {
    const w = mountCanvas(true)
    expect(w.findAll('[data-testid="mode-edit"]')).toHaveLength(1)
    expect(w.text()).not.toContain('只读：agent 正在运行')
  })

  it('文件渲染视图用 static 模式：默认 streaming 模式会给整篇文档的每个文字片段排入场动画，刷新进入时主线程卡十几秒', async () => {
    const w = mountCanvas()
    await flushPromises()
    expect(w.get('[data-testid="rendered"]').attributes('mode')).toBe('static')
  })

  it('切到编辑显示编辑器，切回渲染显示渲染视图', async () => {
    const w = mountCanvas()
    await flushPromises()
    expect(w.find('[data-testid="rendered"]').exists()).toBe(true)
    await w.get('[data-testid="mode-edit"]').trigger('click')
    expect(w.find('[data-testid="code-editor"]').exists()).toBe(true)
    await w.get('[data-testid="mode-view"]').trigger('click')
    expect(w.find('[data-testid="code-editor"]').exists()).toBe(false)
  })

  it('编辑中切到笔记标签或换一份笔记：回到渲染，不把编辑状态带到另一份文件', async () => {
    const w = mountCanvas()
    await flushPromises()
    await w.get('[data-testid="mode-edit"]').trigger('click')
    await w.get('[data-testid="tab-notes"]').trigger('click')
    await flushPromises()
    expect(w.get('[data-testid="mode-edit"]').attributes('aria-pressed')).toBe('false')
    await w.get('[data-testid="mode-edit"]').trigger('click')
    const buttons = w.get('[data-testid="notes-list"]').findAll('button')
    await buttons[1]!.trigger('click')
    await flushPromises()
    expect(w.get('[data-testid="mode-edit"]').attributes('aria-pressed')).toBe('false')
  })

  it('编辑中 agent 开始运行：退出编辑，编辑按钮置灰', async () => {
    const w = mountCanvas()
    await flushPromises()
    await w.get('[data-testid="mode-edit"]').trigger('click')
    await w.setProps({ busy: true })
    await flushPromises()
    expect(w.get('[data-testid="mode-edit"]').attributes('aria-pressed')).toBe('false')
    expect(w.get('[data-testid="mode-edit"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="code-editor"]').exists()).toBe(false)
  })
})
