import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { ApiError } from '@/api/http'
import { invalidateStyleDraft } from '@/composables/queries'
import { entry, resetServer, seedStyle, server } from '@/test/fakeStyleApi'

vi.mock('@/api/endpoints', async () => (await import('@/test/fakeStyleApi')).endpoints)
vi.mock('./StyleChatPane.vue', () => ({
  default: {
    name: 'StyleChatPaneStub',
    props: ['styleId', 'beforeSend'],
    setup: (props: { styleId?: string }) => () =>
      h('div', { 'data-testid': 'chat-pane', 'data-style-id': props.styleId }),
  },
}))
vi.mock('@/components/CodeEditor.vue', () => ({
  default: {
    props: ['content', 'language', 'readonly'],
    emits: ['update:content'],
    setup(props: Record<string, unknown>, { emit }: { emit: (e: 'update:content', v: string) => void }) {
      return () =>
        h('textarea', {
          'data-testid': 'code-editor',
          'data-language': props.language,
          value: props.content,
          disabled: props.readonly,
          onInput: (e: Event) => emit('update:content', (e.target as HTMLTextAreaElement).value),
        })
    },
  },
}))

import StyleEditView from './StyleEditView.vue'

async function settle() {
  await flushPromises()
  await vi.advanceTimersByTimeAsync(0)
  await flushPromises()
}

let lastClient: QueryClient

async function mountEdit(styleId = 's1', props: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  lastClient = queryClient
  const wrapper = mount(StyleEditView, {
    props: { styleId, ...props },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  await settle()
  return wrapper
}

const editor = (w: Awaited<ReturnType<typeof mountEdit>>) =>
  w.get('[data-testid="code-editor"]').element as HTMLTextAreaElement

beforeEach(() => {
  vi.useFakeTimers()
  resetServer()
  seedStyle('s1', '暖纸双色', { 'references/color.md': '主色：暖白' })
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('StyleEditView 显示', () => {
  it('打开草稿后显示表单、文件树和入口内容', async () => {
    const w = await mountEdit()
    expect((w.get('[data-testid="style-name"]').element as HTMLInputElement).value).toBe('暖纸双色')
    expect(w.find('[data-testid="file-references/color.md"]').exists()).toBe(true)
    expect(editor(w).value).toBe(entry('暖纸双色'))
    expect(editor(w).dataset.language).toBe('markdown')
  })

  it('风格不存在时显示提示和关闭按钮', async () => {
    const w = await mountEdit('missing')
    expect(w.get('[data-testid="style-not-found"]').text()).toContain('风格不存在')
    await w.get('[data-testid="style-not-found-close"]').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('点另一个文件显示它的内容，.json 用 json 语言', async () => {
    seedStyle('s2', '带金样本', { 'exemplars/e1.json': '{"a":1}' })
    const w = await mountEdit('s2')

    await w.get('[data-testid="file-exemplars/e1.json"]').trigger('click')
    await settle()

    expect(editor(w).value).toBe('{"a":1}')
    expect(editor(w).dataset.language).toBe('json')
  })
})

describe('StyleEditView 编辑草稿', () => {
  it('敲字后 600ms 写入草稿，状态从「待写入」变成「已保存到草稿」', async () => {
    const w = await mountEdit()
    await w.get('[data-testid="file-references/color.md"]').trigger('click')
    await settle()

    await w.get('[data-testid="code-editor"]').setValue('主色：深蓝')
    expect(w.get('[data-testid="save-state"]').text()).toContain('待写入')
    await vi.advanceTimersByTimeAsync(600)
    await settle()

    expect(server.drafts.get('s1')!['references/color.md']).toBe('主色：深蓝')
    expect(server.saved.get('s1')!['references/color.md']).toBe('主色：暖白')
    expect(w.get('[data-testid="save-state"]').text()).toContain('已保存到草稿')
  })

  it('改名称写进 STYLE.md 的 frontmatter，编辑器里也看得到', async () => {
    const w = await mountEdit()

    await w.get('[data-testid="style-name"]').setValue('新名字')
    await vi.advanceTimersByTimeAsync(600)
    await settle()

    expect(editor(w).value).toContain('name: 新名字')
    expect(server.drafts.get('s1')!['STYLE.md']).toContain('name: 新名字')
  })

  it('添加文件：写出空文件并切到它', async () => {
    const w = await mountEdit()

    await w.get('[data-testid="add-references"]').trigger('click')
    await w.get('[data-testid="new-file-name"]').setValue('palette.md')
    await w.get('[data-testid="new-file-name"]').trigger('keydown', { key: 'Enter' })
    await settle()

    expect(server.drafts.get('s1')!['references/palette.md']).toBe('')
    expect(w.find('[data-testid="file-references/palette.md"]').exists()).toBe(true)
    expect(editor(w).value).toBe('')
  })

  it('删除文件', async () => {
    const w = await mountEdit()

    await w.get('[data-testid="delete-references/color.md"]').trigger('click')
    await settle()

    expect('references/color.md' in server.drafts.get('s1')!).toBe(false)
    expect(w.find('[data-testid="file-references/color.md"]').exists()).toBe(false)
  })

  it('草稿写入失败时显示原因', async () => {
    const w = await mountEdit()
    server.writeError = new ApiError(500, '磁盘已满')

    await w.get('[data-testid="code-editor"]').setValue('x')
    await vi.advanceTimersByTimeAsync(600)
    await settle()

    expect(w.get('[data-testid="save-state"]').text()).toContain('磁盘已满')
  })
})

describe('StyleEditView 保存与放弃', () => {
  it('保存成功：先写出未写入的编辑，再通知上层', async () => {
    const w = await mountEdit()
    await w.get('[data-testid="style-category"]').setValue('科普')

    await w.get('[data-testid="save-style"]').trigger('click')
    await settle()

    expect(server.saved.get('s1')!['STYLE.md']).toContain('category: 科普')
    expect(w.emitted('saved')).toHaveLength(1)
    expect((w.emitted('saved')![0]![0] as { id: string }).id).toBe('s1')
  })

  it('保存失败（422）：显示后端的逐条原因，不通知上层，草稿还在', async () => {
    const w = await mountEdit()
    server.saveError = new ApiError(422, 'STYLE.md 的 frontmatter 缺少非空的 name；references/a.md 过长')

    await w.get('[data-testid="save-style"]').trigger('click')
    await settle()

    expect(w.get('[data-testid="style-server-error"]').text()).toContain('缺少非空的 name')
    expect(w.emitted('saved')).toBeUndefined()
    expect(server.drafts.has('s1')).toBe(true)
  })

  it('保存失败（409 重名）也显示原因', async () => {
    const w = await mountEdit()
    server.saveError = new ApiError(409, '已有同名的风格：暖纸双色')

    await w.get('[data-testid="save-style"]').trigger('click')
    await settle()

    expect(w.get('[data-testid="style-server-error"]').text()).toContain('已有同名的风格')
  })

  it('放弃修改：确认后丢弃草稿，已有风格回到查看', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const w = await mountEdit()

    await w.get('[data-testid="discard-style"]').trigger('click')
    await settle()

    expect(server.drafts.has('s1')).toBe(false)
    expect(w.emitted('discarded')).toEqual([[false]])
  })

  it('放弃修改：新建的从未保存的风格整个消失', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.drafts.set('n1', { 'STYLE.md': entry('新风格') })
    const w = await mountEdit('n1')

    await w.get('[data-testid="discard-style"]').trigger('click')
    await settle()

    expect(w.emitted('discarded')).toEqual([[true]])
  })

  it('取消确认框就什么都不做', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const w = await mountEdit()

    await w.get('[data-testid="discard-style"]').trigger('click')
    await settle()

    expect(server.drafts.has('s1')).toBe(true)
    expect(w.emitted('discarded')).toBeUndefined()
  })

  it('后端拒绝放弃（409）时界面显示原因，不触发 discarded，草稿保留', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const w = await mountEdit()
    server.discardError = new ApiError(409, 'AI 正在修改这套风格，请等这一轮结束（或先停止它）')

    await w.get('[data-testid="discard-style"]').trigger('click')
    await settle()

    expect(w.get('[data-testid="style-server-error"]').text()).toContain('AI 正在修改这套风格')
    expect(w.emitted('discarded')).toBeUndefined()
    expect(server.drafts.has('s1')).toBe(true)
  })
})

describe('StyleEditView 只读（AI 正在修改时）', () => {
  it('编辑器、表单、文件操作和保存按钮都不可用，并说明原因', async () => {
    const w = await mountEdit('s1', { readonly: true, readonlyReason: 'AI 正在修改' })

    expect(editor(w).disabled).toBe(true)
    expect(w.get('[data-testid="style-name"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="add-references"]').exists()).toBe(false)
    expect(w.get('[data-testid="save-style"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="discard-style"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('AI 正在修改')
  })
})

describe('StyleEditView 右侧的 AI 对话区', () => {
  it('编辑态右侧嵌入这套风格的对话区', async () => {
    const w = await mountEdit()
    expect(w.get('[data-testid="chat-pane"]').attributes('data-style-id')).toBe('s1')
  })

  it('发送消息前先把还没写出的编辑写进草稿（否则轮次开始后写入会被 409 拒绝）', async () => {
    const w = await mountEdit()
    await w.get('[data-testid="style-category"]').setValue('科普')
    expect(server.writes).toEqual([])

    const beforeSend = w.getComponent({ name: 'StyleChatPaneStub' }).props('beforeSend') as () => Promise<void>
    await beforeSend()

    expect(server.drafts.get('s1')!['STYLE.md']).toContain('category: 科普')
  })

  it('写不进草稿时发送被拒绝，并给出原因', async () => {
    const w = await mountEdit()
    server.writeError = new ApiError(500, '磁盘已满')
    await w.get('[data-testid="style-category"]').setValue('科普')

    const beforeSend = w.getComponent({ name: 'StyleChatPaneStub' }).props('beforeSend') as () => Promise<void>

    await expect(beforeSend()).rejects.toThrow('磁盘已满')
  })
})

describe('StyleEditView AI 正在修改（后端 busy）', () => {
  it('草稿状态 busy 时整个编辑区只读并说明原因；轮次结束刷新后恢复', async () => {
    server.busy.add('s1')
    const w = await mountEdit()

    expect(editor(w).disabled).toBe(true)
    expect(w.get('[data-testid="style-name"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="save-style"]').attributes('disabled')).toBeDefined()
    expect(w.get('[data-testid="save-state"]').text()).toContain('AI 正在修改')

    server.busy.delete('s1')
    invalidateStyleDraft(lastClient, 's1')
    await settle()

    expect(editor(w).disabled).toBe(false)
    expect(w.get('[data-testid="save-style"]').attributes('disabled')).toBeUndefined()
  })

  it('AI 改了草稿（刷新草稿后）编辑器和文件树显示新内容', async () => {
    const w = await mountEdit()
    server.drafts.get('s1')!['STYLE.md'] = entry('AI 改过的名字')
    server.drafts.get('s1')!['references/new.md'] = 'AI 新建的文件'

    invalidateStyleDraft(lastClient, 's1')
    await settle()

    expect(editor(w).value).toContain('AI 改过的名字')
    expect(w.find('[data-testid="file-references/new.md"]').exists()).toBe(true)
    expect((w.get('[data-testid="style-name"]').element as HTMLInputElement).value).toBe(
      'AI 改过的名字',
    )
  })
})
