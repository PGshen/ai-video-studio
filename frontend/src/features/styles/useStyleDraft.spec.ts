import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { ApiError } from '@/api/http'
import { invalidateStyleDraft, queryKeys } from '@/composables/queries'
import { endpoints, entry, resetServer, seedStyle, server } from '@/test/fakeStyleApi'

vi.mock('@/api/endpoints', async () => (await import('@/test/fakeStyleApi')).endpoints)

import { useStyleDraft } from './useStyleDraft'

function setup(styleId = 's1', sharedClient?: QueryClient) {
  const id = ref(styleId)
  const queryClient =
    sharedClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let draft!: ReturnType<typeof useStyleDraft>
  const wrapper = mount(
    defineComponent({
      setup() {
        draft = useStyleDraft(id)
        return () => null
      },
    }),
    { global: { plugins: [[VueQueryPlugin, { queryClient }]] } },
  )
  return { wrapper, id, queryClient, draft }
}

async function settle() {
  await flushPromises()
  await vi.advanceTimersByTimeAsync(0)
  await flushPromises()
}

beforeEach(() => {
  vi.useFakeTimers()
  resetServer()
  seedStyle('s1', '暖纸双色', { 'references/color.md': '主色：暖白' })
})
afterEach(() => {
  vi.useRealTimers()
})

describe('打开草稿', () => {
  it('打开后给出文件列表和入口内容，默认选中 STYLE.md', async () => {
    const { draft } = setup()
    await settle()

    expect(draft.ready.value).toBe(true)
    expect(draft.files.value).toEqual(['STYLE.md', 'references/color.md'])
    expect(draft.activePath.value).toBe('STYLE.md')
    expect(draft.content.value).toBe(entry('暖纸双色'))
    expect(draft.meta.value.name).toBe('暖纸双色')
    expect(server.drafts.has('s1')).toBe(true)
  })

  it('风格不存在时 notFound，不是 ready', async () => {
    const { draft } = setup('missing')
    await settle()

    expect(draft.notFound.value).toBe(true)
    expect(draft.ready.value).toBe(false)
  })

  it('入口内容还没读到时不是 ready，当前文件还没读到时 contentReady 为假（避免空白闪一下）', async () => {
    const original = endpoints.readDraftFile
    const releases: (() => void)[] = []
    endpoints.readDraftFile = (id, path) =>
      new Promise<string>((resolve) => {
        releases.push(() => resolve(original(id, path)))
      })
    try {
      const { draft } = setup()
      await settle()
      expect(draft.ready.value).toBe(false)
      expect(draft.contentReady.value).toBe(false)

      releases.forEach((release) => release())
      await settle()
      expect(draft.ready.value).toBe(true)
      expect(draft.contentReady.value).toBe(true)
    } finally {
      endpoints.readDraftFile = original
    }
  })

  it('选另一个文件后显示它的内容', async () => {
    const { draft } = setup()
    await settle()

    draft.selectFile('references/color.md')
    await settle()

    expect(draft.content.value).toBe('主色：暖白')
  })
})

describe('AI 正在修改（busy）', () => {
  it('busy 来自草稿状态；轮次结束后刷新草稿就恢复', async () => {
    server.busy.add('s1')
    const { draft, queryClient } = setup()
    await settle()
    expect(draft.busy.value).toBe(true)

    server.busy.delete('s1')
    invalidateStyleDraft(queryClient, 's1')
    await settle()

    expect(draft.busy.value).toBe(false)
  })

  it('没有草稿状态时不是 busy', async () => {
    const { draft } = setup('missing')
    await settle()
    expect(draft.busy.value).toBe(false)
  })
})

describe('编辑与防抖写入', () => {
  it('编辑立即体现在内容里，600ms 后只写一次最后的内容', async () => {
    const { draft } = setup()
    await settle()

    draft.edit('references/color.md', 'a')
    draft.edit('references/color.md', 'ab')
    draft.edit('references/color.md', 'abc')
    expect(draft.saveState.value).toBe('pending')
    await vi.advanceTimersByTimeAsync(599)
    expect(server.writes).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    await settle()

    expect(server.writes).toEqual([{ id: 's1', path: 'references/color.md', content: 'abc' }])
    expect(draft.saveState.value).toBe('saved')
  })

  it('编辑当前文件时 content 马上变，不等服务端', async () => {
    const { draft } = setup()
    await settle()
    draft.selectFile('references/color.md')
    await settle()

    draft.edit('references/color.md', '新的配色')

    expect(draft.content.value).toBe('新的配色')
  })

  it('flush 立即写出，不等防抖', async () => {
    const { draft } = setup()
    await settle()

    draft.edit('references/color.md', 'x')
    await draft.flush()

    expect(server.writes).toHaveLength(1)
    expect(draft.saveState.value).toBe('saved')
  })

  it('组件卸载时把还没写出的编辑写出去（关闭抽屉不丢字）', async () => {
    const { draft, wrapper } = setup()
    await settle()
    draft.edit('references/color.md', '关抽屉前改的')

    wrapper.unmount()
    await settle()

    expect(server.writes.at(-1)).toEqual({
      id: 's1',
      path: 'references/color.md',
      content: '关抽屉前改的',
    })
  })

  it('写失败时 saveState 为 error 并给出原因，之后再编辑还能重试', async () => {
    const { draft } = setup()
    await settle()
    server.writeError = new ApiError(500, '磁盘已满')

    draft.edit('references/color.md', 'x')
    await draft.flush()
    expect(draft.saveState.value).toBe('error')
    expect(draft.writeError.value).toBe('磁盘已满')

    server.writeError = null
    draft.edit('references/color.md', 'xy')
    await draft.flush()
    expect(draft.saveState.value).toBe('saved')
    expect(draft.writeError.value).toBeNull()
  })

  it('一次写入期间又有新编辑时，缓存不会被旧内容覆盖', async () => {
    const { draft, queryClient } = setup()
    await settle()

    draft.edit('references/color.md', 'one')
    await vi.advanceTimersByTimeAsync(600)
    draft.edit('references/color.md', 'one two')
    await settle()

    expect(
      queryClient.getQueryData(queryKeys.styleDraftFile('s1', 'references/color.md')),
    ).toBe('one two')
  })
})

describe('名称、分类、简介（frontmatter）', () => {
  it('updateMeta 改写 STYLE.md 的 frontmatter 并写入草稿', async () => {
    const { draft } = setup()
    await settle()

    draft.updateMeta({ name: '新名字', category: '科普' })
    await draft.flush()

    expect(draft.meta.value).toMatchObject({ name: '新名字', category: '科普' })
    expect(server.drafts.get('s1')!['STYLE.md']).toContain('name: 新名字')
    expect(server.saved.get('s1')!['STYLE.md']).toContain('name: 暖纸双色')
  })

  it('正在看别的文件时也能改 STYLE.md 的元信息', async () => {
    const { draft } = setup()
    await settle()
    draft.selectFile('references/color.md')
    await settle()

    draft.updateMeta({ description: '换了简介' })
    await draft.flush()

    expect(draft.meta.value.description).toBe('换了简介')
    expect(draft.content.value).toBe('主色：暖白')
  })
})

describe('增删文件', () => {
  it('addFile 写出空文件并选中它', async () => {
    const { draft } = setup()
    await settle()

    await draft.addFile('exemplars', 'e1.json')
    await settle()

    expect(draft.files.value).toContain('exemplars/e1.json')
    expect(draft.activePath.value).toBe('exemplars/e1.json')
  })

  it('removeFile 删除文件；删的是当前文件时回到 STYLE.md', async () => {
    const { draft } = setup()
    await settle()
    draft.selectFile('references/color.md')
    await settle()

    await draft.removeFile('references/color.md')
    await settle()

    expect(draft.files.value).toEqual(['STYLE.md'])
    expect(draft.activePath.value).toBe('STYLE.md')
  })

  it('刚敲的字还在防抖里时删另一个文件，不会被冲回旧内容，之后照常写出', async () => {
    const { draft } = setup()
    await settle()

    draft.edit('STYLE.md', entry('刚敲的新名字'))
    await draft.removeFile('references/color.md')
    await settle()

    expect(draft.entryText.value).toBe(entry('刚敲的新名字'))
    expect(draft.content.value).toBe(entry('刚敲的新名字'))
    await draft.flush()
    expect(server.drafts.get('s1')!['STYLE.md']).toBe(entry('刚敲的新名字'))
  })
})

describe('保存与放弃', () => {
  it('保存前先写出未写入的编辑，成功后返回正式版本', async () => {
    const { draft } = setup()
    await settle()
    draft.edit('references/color.md', '深蓝')

    const saved = await draft.save()

    expect(saved?.files['references/color.md']).toBe('深蓝')
    expect(server.saved.get('s1')!['references/color.md']).toBe('深蓝')
    expect(server.drafts.has('s1')).toBe(false)
  })

  it('保存失败（422）时给出逐条原因，草稿保留', async () => {
    const { draft } = setup()
    await settle()
    server.saveError = new ApiError(422, 'STYLE.md 的 frontmatter 缺少非空的 name')

    const saved = await draft.save()

    expect(saved).toBeNull()
    expect(draft.saveError.value).toBe('STYLE.md 的 frontmatter 缺少非空的 name')
    expect(server.drafts.has('s1')).toBe(true)
  })

  it('放弃修改：已有风格回到正式版本；新建的从未保存的风格整个消失', async () => {
    const { draft } = setup()
    await settle()
    expect(await draft.discard()).toEqual({ wasNew: false })
    expect(server.drafts.has('s1')).toBe(false)
    expect(server.saved.has('s1')).toBe(true)

    server.drafts.set('n1', { 'STYLE.md': entry('新风格') })
    const fresh = setup('n1')
    await settle()
    expect(await fresh.draft.discard()).toEqual({ wasNew: true })
    expect(server.drafts.has('n1')).toBe(false)
  })
})

describe('放弃修改失败', () => {
  it('后端拒绝（409）时返回 null、给出原因，草稿保留', async () => {
    const { draft } = setup()
    await settle()
    server.discardError = new ApiError(409, 'AI 正在修改这套风格，请等这一轮结束（或先停止它）')

    const result = await draft.discard()

    expect(result).toBeNull()
    expect(draft.discardError.value).toBe('AI 正在修改这套风格，请等这一轮结束（或先停止它）')
    expect(server.drafts.has('s1')).toBe(true)
  })

  it('失败时还没写出的编辑不丢，之后照常写出；再次放弃成功后错误清空', async () => {
    const { draft } = setup()
    await settle()
    draft.edit('references/color.md', '深蓝')
    server.discardError = new ApiError(409, '忙')

    expect(await draft.discard()).toBeNull()
    await vi.advanceTimersByTimeAsync(700)
    await settle()
    expect(server.drafts.get('s1')!['references/color.md']).toBe('深蓝')

    server.discardError = null
    expect(await draft.discard()).toEqual({ wasNew: false })
    expect(draft.discardError.value).toBeNull()
  })
})

describe('评审修复：AI 的改动不会被旧缓存或事后重放的编辑覆盖', () => {
  it('编辑视图卸载期间 AI 改了草稿，重新进入时显示新内容而不是旧缓存', async () => {
    const shared = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const first = setup('s1', shared)
    await settle()
    first.wrapper.unmount()

    server.drafts.get('s1')!['STYLE.md'] = entry('AI 在抽屉关闭期间改的名字')
    server.drafts.get('s1')!['references/color.md'] = 'AI 改的配色'
    const second = setup('s1', shared)
    await settle()

    expect(second.draft.content.value).toContain('AI 在抽屉关闭期间改的名字')
    expect(second.draft.meta.value.name).toBe('AI 在抽屉关闭期间改的名字')
    second.draft.selectFile('references/color.md')
    await settle()
    expect(second.draft.content.value).toBe('AI 改的配色')
  })

  it('写入被 409 拒绝（AI 正在修改）的编辑不会留着事后重放，覆盖 AI 的成果', async () => {
    const { draft } = setup()
    await settle()
    server.writeError = new ApiError(409, 'AI 正在修改这套风格，请等这一轮结束')

    draft.edit('references/color.md', '我在锁住之前敲的字')
    await draft.flush()
    expect(draft.saveState.value).toBe('idle')

    server.writeError = null
    server.drafts.get('s1')!['references/color.md'] = 'AI 的成果'
    await draft.flush()
    const saved = await draft.save()

    expect(server.writes.map((w) => w.content)).not.toContain('我在锁住之前敲的字')
    expect(saved?.files['references/color.md']).toBe('AI 的成果')
  })

  it('非 409 的写入失败仍然保留编辑，等下一次重试', async () => {
    const { draft } = setup()
    await settle()
    server.writeError = new ApiError(500, '磁盘已满')

    draft.edit('references/color.md', '要保住的编辑')
    await draft.flush()
    server.writeError = null
    await draft.flush()

    expect(server.drafts.get('s1')!['references/color.md']).toBe('要保住的编辑')
  })
})
