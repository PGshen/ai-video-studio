import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { resetServer, seedDraft, seedStyle, server } from '@/test/fakeStyleApi'

vi.mock('@/api/endpoints', async () => (await import('@/test/fakeStyleApi')).endpoints)
vi.mock('@/components/CodeEditor.vue', () => ({
  default: {
    props: ['content', 'language', 'readonly'],
    setup(props: Record<string, unknown>) {
      return () =>
        h(
          'pre',
          {
            'data-testid': 'code-view',
            // a bare `readonly` attribute reaches an array-declared prop as ''
            'data-readonly': String(props.readonly === '' || props.readonly === true),
          },
          String(props.content),
        )
    },
  },
}))
vi.mock('@/components/session/SafeMarkdown.vue', () => ({
  default: {
    props: ['content'],
    setup: (props: Record<string, unknown>) => () =>
      h('div', { 'data-testid': 'markdown-view' }, String(props.content)),
  },
}))
// 删除按钮自带确认框（走 portal），这里换成点一下就执行 action 的桩。
vi.mock('@/components/ConfirmDeleteButton.vue', () => ({
  default: {
    props: ['testId', 'action'],
    setup(props: Record<string, unknown>) {
      return () =>
        h('button', { 'data-testid': props.testId, onClick: () => void (props.action as () => unknown)() }, '删除')
    },
  },
}))

import StyleDetailView from './StyleDetailView.vue'

async function mountDetail(styleId = 's1', retry: boolean | number = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry } } })
  const wrapper = mount(StyleDetailView, {
    props: { styleId },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  resetServer()
  seedStyle('s1', '暖纸双色', { 'references/color.md': '主色：暖白' })
})

describe('StyleDetailView', () => {
  it('只读显示名称、分类、简介、文件树和入口内容', async () => {
    const w = await mountDetail()

    expect(w.text()).toContain('暖纸双色')
    expect(w.text()).toContain('概念传记')
    expect(w.text()).toContain('一套风格')
    expect(w.find('[data-testid="add-references"]').exists()).toBe(false)
  })

  it('markdown 文件直接渲染，不用编辑器；STYLE.md 去掉 frontmatter（标题区已经显示）', async () => {
    const w = await mountDetail()

    const view = w.get('[data-testid="markdown-view"]')
    expect(view.text()).toContain('# 暖纸双色')
    expect(view.text()).not.toContain('description:')
    expect(w.find('[data-testid="code-view"]').exists()).toBe(false)
  })

  it('切换文件时渲染面板整个换新，不带着上一个文件的滚动位置', async () => {
    const w = await mountDetail()
    const before = w.get('[data-testid="markdown-pane"]').element

    await w.get('[data-testid="file-references/color.md"]').trigger('click')

    expect(w.get('[data-testid="markdown-pane"]').element).not.toBe(before)
  })

  it('json 金样本仍用只读编辑器显示', async () => {
    seedStyle('s2', '带金样本', { 'exemplars/e1.json': '{"a":1}' })
    const w = await mountDetail('s2')

    await w.get('[data-testid="file-exemplars/e1.json"]').trigger('click')

    expect(w.find('[data-testid="markdown-view"]').exists()).toBe(false)
    expect(w.get('[data-testid="code-view"]').attributes('data-readonly')).toBe('true')
    expect(w.get('[data-testid="code-view"]').text()).toBe('{"a":1}')
  })

  it('点文件显示该文件的正式版本内容', async () => {
    const w = await mountDetail()

    await w.get('[data-testid="file-references/color.md"]').trigger('click')

    expect(w.get('[data-testid="markdown-view"]').text()).toBe('主色：暖白')
  })

  it('风格不存在时显示提示', async () => {
    const w = await mountDetail('missing')
    expect(w.get('[data-testid="style-not-found"]').text()).toContain('风格不存在')
  })

  it('风格不存在时立刻提示，不会按默认配置重试好几秒（深链接到已删除的风格）', async () => {
    const w = await mountDetail('missing', 3)
    expect(w.find('[data-testid="style-not-found"]').exists()).toBe(true)
  })

  it('有未保存草稿时提示，并说明详情显示的是正式版本', async () => {
    seedDraft('s1', { 'STYLE.md': 'x' })
    const w = await mountDetail()
    expect(w.get('[data-testid="style-draft-notice"]').text()).toContain('未保存的草稿')
  })

  it('点「编辑」通知上层', async () => {
    const w = await mountDetail()
    await w.get('[data-testid="detail-edit"]').trigger('click')
    expect(w.emitted('edit')).toHaveLength(1)
  })

  it('设为默认 / 取消默认', async () => {
    const w = await mountDetail()

    await w.get('[data-testid="toggle-default"]').trigger('click')
    await flushPromises()
    expect(server.defaultId).toBe('s1')
    expect(w.get('[data-testid="toggle-default"]').text()).toBe('取消默认')

    await w.get('[data-testid="toggle-default"]').trigger('click')
    await flushPromises()
    expect(server.defaultId).toBeNull()
  })

  it('复制后通知上层打开新的副本', async () => {
    const w = await mountDetail()

    await w.get('[data-testid="duplicate-style"]').trigger('click')
    await flushPromises()

    const [newId] = w.emitted('open')![0] as [string]
    expect(newId).not.toBe('s1')
    expect(server.saved.has(newId)).toBe(true)
  })

  it('删除后通知上层关闭', async () => {
    const w = await mountDetail()

    await w.get('[data-testid="style-delete"]').trigger('click')
    await flushPromises()

    expect(server.saved.has('s1')).toBe(false)
    expect(w.emitted('close')).toHaveLength(1)
  })
})
