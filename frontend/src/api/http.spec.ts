import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, encodeFilePath, encodePathSegment, request, requestText } from '@/api/http'

describe('request', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('GET 请求打到 /api 前缀，返回解析后的 JSON', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ id: 'p1' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await request<{ id: string }>('/projects/p1')

    expect(result).toEqual({ id: 'p1' })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url)).toBe('/api/projects/p1')
    expect(init.method).toBe('GET')
  })

  it('POST 请求带 JSON body 和 Content-Type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/projects', { method: 'POST', body: { title: 'demo' } })

    const [, init] = fetchMock.mock.calls[0]!
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(init.body).toBe(JSON.stringify({ title: 'demo' }))
  })

  it('query 参数拼进 URL，忽略 null/undefined', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/projects/p1/snapshots/diff', { query: { from: 'a', to: 'b', skip: null } })

    const [url] = fetchMock.mock.calls[0]!
    expect(String(url)).toBe('/api/projects/p1/snapshots/diff?from=a&to=b')
  })

  it('非 2xx 响应抛 ApiError，带上状态码和 detail', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: '会话正忙' }), { status: 409 }))
    vi.stubGlobal('fetch', fetchMock)

    const error = await request('/sessions/s1/messages', { method: 'POST', body: {} }).catch(
      (e: unknown) => e,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).detail).toBe('会话正忙')
  })

  it('204/空响应体返回 undefined', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await request('/projects/p1/stages/topic/finalize', { method: 'POST' })

    expect(result).toBeUndefined()
  })
})

describe('requestText', () => {
  it('按文本返回文件内容', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('# hello', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const text = await requestText('/projects/p1/files/style/STYLE.md')

    expect(text).toBe('# hello')
  })

  it('非 2xx 同样抛 ApiError', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('未知阶段', { status: 404 }))
    vi.stubGlobal('fetch', fetchMock)

    const error = await requestText('/projects/p1/files/missing.md').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
  })
})

describe('encodePathSegment / encodeFilePath', () => {
  it('encodePathSegment 编码单个动态段里的特殊字符', () => {
    // `#` 会被当成 URL fragment 起点，`?` 会被当成 query 起点，
    // 都必须编码掉，否则名字含这些字符的项目/会话/快照 id 会拼出错误的路径。
    expect(encodePathSegment('proj#1')).toBe('proj%231')
    expect(encodePathSegment('a?b=c')).toBe('a%3Fb%3Dc')
    expect(encodePathSegment('a b')).toBe('a%20b')
    expect(encodePathSegment('a/b')).toBe('a%2Fb') // 单个段里的 `/` 也要编码。
  })

  it('encodeFilePath 保留 / 分隔符，只编码每一段内部的特殊字符', () => {
    expect(encodeFilePath('topic/fake note.md')).toBe('topic/fake%20note.md')
    expect(encodeFilePath('a#b/c?d')).toBe('a%23b/c%3Fd')
  })

  it('GET 请求里名字含特殊字符的路径段会被正确编码并原样送到 fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await request(`/projects/${encodePathSegment('proj#1')}`)

    const [url] = fetchMock.mock.calls[0]!
    expect(String(url)).toBe('/api/projects/proj%231')
  })
})
