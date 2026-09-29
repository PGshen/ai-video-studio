import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createIdea,
  createProject,
  createRenderJob,
  createSession,
  finalizeRender,
  finalVideoUrl,
  getFileContent,
  getJob,
  getProject,
  getSession,
  getTopicCheck,
  listIdeas,
  sessionStreamUrl,
  updateIdea,
  workspaceFileUrl,
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

  it('createRenderJob 对 projectId 编码，POST 到 .../render', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await createRenderJob('p 1')

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/projects/p%201/render')
    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ method: 'POST' })
  })

  it('getJob 对 projectId 和 jobId 都编码', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await getJob('p 1', 'j#1')

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/projects/p%201/jobs/j%231')
  })

  it('finalizeRender 对 projectId 编码，POST 到 .../animation/finalize-render', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await finalizeRender('p 1')

    expect(String(fetchMock.mock.calls[0]![0])).toBe(
      '/api/projects/p%201/animation/finalize-render',
    )
    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ method: 'POST' })
  })

  it('finalVideoUrl 对 projectId 编码，不发请求', () => {
    expect(finalVideoUrl('p 1')).toBe('/api/projects/p%201/output/final.mp4')
  })

  it('workspaceFileUrl 对 projectId 和路径逐段编码，version 拼进查询串', () => {
    expect(workspaceFileUrl('p 1', 'narrative/audio/s a.mp3')).toBe(
      '/api/projects/p%201/files/narrative/audio/s%20a.mp3',
    )
    expect(workspaceFileUrl('p', 'narrative/audio/s-a.mp3', 'sha256:ab')).toBe(
      '/api/projects/p/files/narrative/audio/s-a.mp3?v=sha256%3Aab',
    )
  })

  it('listIdeas 不带状态时不加查询串，带状态时走 status', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response('[]', { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)

    await listIdeas()
    await listIdeas('archived')

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/ideas')
    expect(String(fetchMock.mock.calls[1]![0])).toBe('/api/ideas?status=archived')
  })

  it('createIdea POST 到 /ideas，updateIdea PATCH 并对 id 编码', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)

    await createIdea({ title: 'T' })
    await updateIdea('i#1', { pitch: null })

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/ideas')
    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ method: 'POST' })
    expect(String(fetchMock.mock.calls[1]![0])).toBe('/api/ideas/i%231')
    expect(fetchMock.mock.calls[1]![1]).toMatchObject({ method: 'PATCH' })
    expect(JSON.parse(String(fetchMock.mock.calls[1]![1].body))).toEqual({ pitch: null })
  })

  it('createProject 可以带 idea_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await createProject({ title: 'P', idea_id: 'i1' })

    expect(JSON.parse(String(fetchMock.mock.calls[0]![1].body))).toEqual({
      title: 'P',
      idea_id: 'i1',
    })
  })

  it('getTopicCheck 对 projectId 编码', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await getTopicCheck('p 1')

    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/projects/p%201/topic/check')
  })
})
