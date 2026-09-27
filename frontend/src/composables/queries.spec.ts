import { QueryClient } from '@tanstack/vue-query'
import { describe, expect, it, vi } from 'vitest'
import { invalidateWorkspace, queryKeys } from '@/composables/queries'

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
  })
})

describe('invalidateWorkspace', () => {
  it('按前缀失效文件树、文件内容和快照列表', async () => {
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    await invalidateWorkspace(queryClient, 'p1')

    // vue-query 的 `invalidateQueries` 类型上允许 `filters` 是一个返回 filters 的函数
    // （方便传 `ref`/getter），但 `invalidateWorkspace` 永远直接传对象字面量，测试
    // 断言时按对象形状收窄即可。
    const keys = spy.mock.calls.map((call) => (call[0] as { queryKey?: unknown[] } | undefined)?.queryKey)
    expect(keys).toContainEqual(['projects', 'p1', 'files'])
    expect(keys).toContainEqual(['projects', 'p1', 'snapshots'])
  })
})
