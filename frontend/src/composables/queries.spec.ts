import { QueryClient } from '@tanstack/vue-query'
import { describe, expect, it, vi } from 'vitest'
import {
  invalidateAfterWrite,
  invalidateWorkspace,
  jobRefetchIntervalMs,
  queryKeys,
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
})
