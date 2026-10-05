import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  encodeFilePath,
  encodePathSegment,
  errorMessage,
  request,
  requestText,
  uploadForm,
} from '@/api/http'
import { FakeXhr } from '@/test/fakeXhr'

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

describe('errorMessage', () => {
  it('字符串 detail 原样返回', () => {
    expect(errorMessage(new ApiError(409, '配置正被 2 个会话使用'))).toBe('配置正被 2 个会话使用')
  })

  it('FastAPI 校验错误列表逐条拼起来，去掉 body 前缀', () => {
    const detail = [
      { loc: ['body', 'nope'], msg: 'Extra inputs are not permitted' },
      { loc: ['body', 'speed'], msg: 'Input should be a valid number' },
    ]

    expect(errorMessage(new ApiError(422, detail))).toBe(
      'nope：Extra inputs are not permitted；speed：Input should be a valid number',
    )
  })

  it('空列表或未知结构回退到默认文案', () => {
    expect(errorMessage(new ApiError(500, []))).toBe('请求失败（500）')
    expect(errorMessage(new ApiError(500, null))).toBe('请求失败（500）')
  })

  it('普通 Error 用它的 message，其他值是未知错误', () => {
    expect(errorMessage(new Error('断网了'))).toBe('断网了')
    expect(errorMessage('boom')).toBe('未知错误')
  })
})

describe('uploadForm', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeXhr.reset()
  })

  function form(): FormData {
    const data = new FormData()
    data.append('file', new File(['abc'], 'a.mp3'))
    return data
  }

  it('POST 到 /api 前缀，不手设 Content-Type，2xx 解析 JSON', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const data = form()
    const promise = uploadForm<{ ok: boolean }>('/projects/p1/music/source', data)
    const xhr = FakeXhr.last
    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe('/api/projects/p1/music/source')
    expect(xhr.body).toBe(data)
    expect(xhr.headers).toEqual({})
    xhr.respond(200, { ok: true })
    await expect(promise).resolves.toEqual({ ok: true })
  })

  it('上传进度回调给出已传与总量', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const seen: Array<[number, number]> = []
    const promise = uploadForm('/x', form(), { onProgress: (loaded, total) => seen.push([loaded, total]) })
    FakeXhr.last.progress(10, 40)
    FakeXhr.last.progress(40, 40)
    FakeXhr.last.respond(200, {})
    await promise
    expect(seen).toEqual([
      [10, 40],
      [40, 40],
    ])
  })

  it('非 2xx 抛 ApiError，detail 沿用后端的 detail', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const promise = uploadForm('/x', form())
    FakeXhr.last.respond(422, { detail: '文件大小超过上限 150 MB' })
    const error = await promise.catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).detail).toBe('文件大小超过上限 150 MB')
  })

  it('网络错误抛 Error，不是 ApiError', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const promise = uploadForm('/x', form())
    FakeXhr.last.fail()
    const error = await promise.catch((e: unknown) => e)
    expect(error).toBeInstanceOf(Error)
    expect(error).not.toBeInstanceOf(ApiError)
  })

  it('signal 触发时中止请求并以 AbortError 结束', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const controller = new AbortController()
    const promise = uploadForm('/x', form(), { signal: controller.signal })
    controller.abort()
    expect(FakeXhr.last.aborted).toBe(true)
    const error = await promise.catch((e: unknown) => e)
    expect((error as Error).name).toBe('AbortError')
  })

  it('已经中止的 signal 不发请求', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const controller = new AbortController()
    controller.abort()
    const error = await uploadForm('/x', form(), { signal: controller.signal }).catch((e: unknown) => e)
    expect((error as Error).name).toBe('AbortError')
    expect(FakeXhr.instances).toHaveLength(0)
  })
})
