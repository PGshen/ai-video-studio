import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import { ApiError } from '@/api/http'

const state = vi.hoisted(() => ({
  files: [] as { path: string; readonly: boolean }[],
  content: 'hello',
  mutateAsync: vi.fn(),
  reveal: vi.fn(),
}))

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  revealInFileManager: state.reveal,
}))

vi.mock('@/composables/queries', () => ({
  useFileTreeQuery: () => ({ data: ref({ files: state.files }), dataUpdatedAt: ref(7) }),
  useFileContentQuery: (_project: unknown, path: () => string | null) => ({
    data: computed(() => (path() ? state.content : undefined)),
    isPending: ref(false),
  }),
  useWriteFileMutation: () => ({ mutateAsync: state.mutateAsync, isPending: ref(false) }),
}))
vi.mock('@/components/CodeEditor.vue', () => ({
  default: {
    props: ['content', 'language', 'readonly'],
    emits: ['update:content'],
    template: '<textarea data-testid="code-editor" :value="content" @input="$emit(\'update:content\', $event.target.value)" />',
  },
}))

import FileCanvas from './FileCanvas.vue'
import FileTree from './FileTree.vue'

async function mountWith(path: string) {
  state.files = [{ path, readonly: false }]
  const wrapper = mount(FileCanvas, { props: { projectId: 'p1', stage: 'open', busy: false } })
  wrapper.findComponent(FileTree).vm.$emit('select', path)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  state.mutateAsync.mockReset()
  state.reveal.mockReset()
  state.content = 'hello'
})

describe('FileCanvas 的 HTML 预览（open-mode 设计 §7）', () => {
  it('HTML 文件默认显示预览：iframe 指向原始文件端点，只放行脚本、不给同源', async () => {
    const wrapper = await mountWith('site/index.html')

    const frame = wrapper.get('iframe[data-testid="html-preview"]')
    expect(frame.attributes('sandbox')).toBe('allow-scripts')
    expect(frame.attributes('src')).toBe('/api/projects/p1/files/site/index.html?v=7')
    expect(wrapper.find('[data-testid="code-editor"]').exists()).toBe(false)
  })

  it('切到源码出现编辑器，切回预览又是 iframe', async () => {
    const wrapper = await mountWith('index.html')

    await wrapper.get('[data-testid="html-view-source"]').trigger('click')
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.get('[data-testid="code-editor"]').element).toBeTruthy()

    await wrapper.get('[data-testid="html-view-preview"]').trigger('click')
    expect(wrapper.find('iframe').exists()).toBe(true)
  })

  it('非 HTML 文件没有预览切换', async () => {
    const wrapper = await mountWith('notes.md')

    expect(wrapper.find('[data-testid="html-view-source"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="code-editor"]').exists()).toBe(true)
  })

  it('保存被拒（403）时提示不在可写范围内，不提阶段', async () => {
    state.mutateAsync.mockRejectedValue(new ApiError(403, 'forbidden'))
    const wrapper = await mountWith('notes.md')
    await wrapper.get('[data-testid="code-editor"]').setValue('changed')

    const save = wrapper.findAll('button').find((b) => b.text() === '保存')!
    await save.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('保存失败：不在可写范围内')
    expect(wrapper.text()).not.toContain('当前阶段')
  })
})

describe('FileCanvas 的「在 Finder 中打开」', () => {
  it('选中文件时显示选中的文件', async () => {
    state.reveal.mockResolvedValue(undefined)
    const wrapper = await mountWith('covers/a.png')

    await wrapper.get('[data-testid="reveal-in-file-manager"]').trigger('click')
    await flushPromises()

    expect(state.reveal).toHaveBeenCalledWith('p1', 'covers/a.png')
  })

  it('没有选中文件时打开工作区根目录', async () => {
    state.reveal.mockResolvedValue(undefined)
    state.files = []
    const wrapper = mount(FileCanvas, { props: { projectId: 'p1', stage: 'open', busy: false } })

    await wrapper.get('[data-testid="reveal-in-file-manager"]').trigger('click')
    await flushPromises()

    expect(state.reveal).toHaveBeenCalledWith('p1', '')
  })

  it('失败时提示错误', async () => {
    state.reveal.mockRejectedValue(new ApiError(500, '无法在文件管理器中显示：x'))
    const wrapper = await mountWith('notes.md')

    await wrapper.get('[data-testid="reveal-in-file-manager"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('无法在文件管理器中显示：x')
  })
})
