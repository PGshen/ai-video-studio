import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { FakeXhr } from '@/test/fakeXhr'
import {
  invalidateAfterWrite,
  invalidateStyleDraft,
  invalidateWorkspace,
  jobRefetchIntervalMs,
  queryKeys,
  useUploadMusicSourceMutation,
} from '@/composables/queries'

describe('queryKeys', () => {
  it('派生的 key 层级和实际的资源路径一致，方便前缀失效', () => {
    expect(queryKeys.projects()).toEqual(['projects'])
    expect(queryKeys.project('p1')).toEqual(['projects', 'p1'])
    expect(queryKeys.fileTree('p1')).toEqual(['projects', 'p1', 'files'])
    expect(queryKeys.fileContent('p1', 'a/b.md')).toEqual(['projects', 'p1', 'files', 'a/b.md'])
    expect(queryKeys.snapshots('p1')).toEqual(['projects', 'p1', 'snapshots'])
    expect(queryKeys.sessions('p1', 'topic')).toEqual(['projects', 'p1', 'stages', 'topic', 'sessions'])
    expect(queryKeys.session('s1')).toEqual(['sessions', 's1'])
    expect(queryKeys.modelProfiles()).toEqual(['model-profiles'])
    expect(queryKeys.settings()).toEqual(['settings'])
    expect(queryKeys.job('j1')).toEqual(['jobs', 'j1'])
    expect(queryKeys.ideasAll()).toEqual(['ideas'])
    expect(queryKeys.brainstormSessions()).toEqual(['brainstorm', 'sessions'])
    expect(queryKeys.sessionsFor({ kind: 'brainstorm' })).toEqual(['brainstorm', 'sessions'])
    expect(queryKeys.sessionsFor({ kind: 'project', projectId: 'p1', stage: 'topic' })).toEqual(
      queryKeys.sessions('p1', 'topic'),
    )
    expect(queryKeys.ideas('archived')).toEqual(['ideas', 'archived'])
    expect(queryKeys.ideas(null)).toEqual(['ideas', 'active'])
    expect(queryKeys.topicCheck('p1')).toEqual(['projects', 'p1', 'topic', 'check'])
    expect(queryKeys.htmlPreviewMeta('p1')).toEqual(['projects', 'p1', 'animation', 'html-preview-meta'])
    expect(queryKeys.musicMeta('p1')).toEqual(['projects', 'p1', 'music', 'meta'])
  })
})

describe('jobRefetchIntervalMs', () => {
  it('queued/running 时 1 秒轮询一次', () => {
    expect(jobRefetchIntervalMs('queued')).toBe(1000)
    expect(jobRefetchIntervalMs('running')).toBe(1000)
  })

  it('done/failed 或还没有数据时停止轮询', () => {
    expect(jobRefetchIntervalMs('done')).toBe(false)
    expect(jobRefetchIntervalMs('failed')).toBe(false)
    expect(jobRefetchIntervalMs(undefined)).toBe(false)
    expect(jobRefetchIntervalMs(null)).toBe(false)
  })
})

describe('invalidateAfterWrite', () => {
  it('手动保存文件后失效文件树、该文件内容和选题简报检查（L4 发现：保存后检查提示条不刷新）', async () => {
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    await invalidateAfterWrite(queryClient, 'p1', 'topic/brief.md')

    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toContainEqual(['projects', 'p1', 'files'])
    expect(keys).toContainEqual(['projects', 'p1', 'files', 'topic/brief.md'])
    expect(keys).toContainEqual(['projects', 'p1', 'topic', 'check'])
    expect(keys).toContainEqual(['projects', 'p1', 'animation', 'html-preview-meta'])
    expect(keys).toContainEqual(['projects', 'p1', 'music', 'meta'])
  })
})

describe('invalidateWorkspace', () => {
  it('按前缀失效文件树、文件内容和快照列表', async () => {
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    await invalidateWorkspace(queryClient, 'p1')

    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toContainEqual(['projects', 'p1', 'files'])
    expect(keys).toContainEqual(['projects', 'p1', 'snapshots'])
  })

  it('工作区变化后也重新取配乐的 meta（节拍脚本变了会让配乐变旧）', async () => {
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    await invalidateWorkspace(queryClient, 'p1')

    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toContainEqual(['projects', 'p1', 'music', 'meta'])
  })

  it('工作区变化后重新取 HTML 预览的 meta（哈希变了才会刷新 iframe）', async () => {
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    await invalidateWorkspace(queryClient, 'p1')

    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toContainEqual(['projects', 'p1', 'animation', 'html-preview-meta'])
  })
})

describe('style queries', () => {
  it('风格的 key 层级：列表 ⊃ 单个风格 ⊃ 草稿 ⊃ 草稿文件，方便前缀失效', () => {
    expect(queryKeys.styles()).toEqual(['styles'])
    expect(queryKeys.style('s1')).toEqual(['styles', 's1'])
    expect(queryKeys.styleDraft('s1')).toEqual(['styles', 's1', 'draft'])
    expect(queryKeys.sessionsFor({ kind: 'style', styleId: 's1' })).toEqual([
      'styles',
      's1',
      'sessions',
    ])
    expect(queryKeys.styleDraftFile('s1', 'references/a.md')).toEqual([
      'styles',
      's1',
      'draft',
      'files',
      'references/a.md',
    ])
  })

  it('invalidateStyleDraft 只失效这套风格的草稿（状态和各文件），不碰列表和别的风格', async () => {
    const queryClient = new QueryClient()
    for (const key of [
      queryKeys.styles(),
      queryKeys.style('s1'),
      queryKeys.styleDraft('s1'),
      queryKeys.styleDraftFile('s1', 'STYLE.md'),
      queryKeys.styleDraft('s2'),
    ]) {
      queryClient.setQueryData(key, 'x')
    }

    invalidateStyleDraft(queryClient, 's1')

    const stale = (key: readonly unknown[]) => queryClient.getQueryState(key)?.isInvalidated
    expect(stale(queryKeys.styleDraft('s1'))).toBe(true)
    expect(stale(queryKeys.styleDraftFile('s1', 'STYLE.md'))).toBe(true)
    expect(stale(queryKeys.styles())).toBe(false)
    expect(stale(queryKeys.style('s1'))).toBe(false)
    expect(stale(queryKeys.styleDraft('s2'))).toBe(false)
  })
})

describe('useUploadMusicSourceMutation', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeXhr.reset()
  })

  it('上传成功后失效配乐 meta、预览 meta 与文件树；进度由调用方的 onProgress 取', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    let mutation!: ReturnType<typeof useUploadMusicSourceMutation>
    const Probe = defineComponent({
      setup() {
        mutation = useUploadMusicSourceMutation('p1')
        return () => null
      },
    })
    mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })

    const seen: number[] = []
    const promise = mutation.mutateAsync({
      file: new File(['abc'], 'a.mp3'),
      onProgress: (loaded) => seen.push(loaded),
    })
    await flushPromises() // the mutation function runs on a later tick
    FakeXhr.last.progress(2, 3)
    FakeXhr.last.respond(200, { filename: 'source.mp3', size: 3, sha256: 'x', duration: 10 })
    await promise
    await flushPromises()

    expect(seen).toEqual([2])
    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toContainEqual(['projects', 'p1', 'music', 'meta'])
    expect(keys).toContainEqual(['projects', 'p1', 'animation', 'html-preview-meta'])
    expect(keys).toContainEqual(['projects', 'p1', 'files'])
  })
})
