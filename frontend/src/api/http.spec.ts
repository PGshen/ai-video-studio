import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, requestText } from '@/api/http'

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
