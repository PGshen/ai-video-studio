import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createSession,
  getFileContent,
  getProject,
  getSession,
  sessionStreamUrl,
  writeFileContent,
} from '@/api/endpoints'

describe('endpoints：动态路径段会被正确编码', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getProject 对含 # 的项目 id 编码', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await getProject('proj#1')

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/projects/proj%231')
  })

  it('getFileContent 保留文件路径里的 /，编码每一段里的特殊字符', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('内容', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await getFileContent('p1', 'topic/fake note?.md')

    expect(String(fetchMock.mock.calls[0]![0])).toBe(
      '/api/projects/p1/files/topic/fake%20note%3F.md',
    )
  })

  it('writeFileContent 同时编码 projectId 和文件路径，stage 走 query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await writeFileContent('p#1', 'a b.md', 'topic', 'hello')

    expect(String(fetchMock.mock.calls[0]![0])).toBe(
      '/api/projects/p%231/files/a%20b.md?stage=topic',
    )
  })

  it('getSession / sessionStreamUrl 对含空格的 session id 编码', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await getSession('s 1')

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/sessions/s%201')
    expect(sessionStreamUrl('s 1')).toBe('/api/sessions/s%201/stream')
  })

  it('createSession 对 projectId 和 stage 都编码', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await createSession('p 1', 'topic?', { model_profile_id: 'm1' })

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/projects/p%201/stages/topic%3F/sessions')
  })
})
