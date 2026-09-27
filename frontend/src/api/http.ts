/**
 * 基于 `fetch` 的小型 HTTP 客户端（任务简报 T12，控制者裁定 2）。
 *
 * 所有请求都打到 `/api`（vite 开发代理转发到后端，见 `vite.config.ts`）；
 * 请求体/响应体统一按 JSON 处理；非 2xx 响应包成 `ApiError`（带 `status` 和
 * 后端 `{"detail": ...}` 里的 `detail`），方便调用方按状态码区分
 * 400/403/404/409 等语义（见各 `api/*.py` 路由文档）。
 */

const BASE_URL = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `请求失败（${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function parseErrorDetail(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    const body = JSON.parse(text) as { detail?: unknown }
    return body.detail ?? body
  } catch {
    return text
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  query?: Record<string, string | number | boolean | null | undefined>
  body?: unknown
  signal?: AbortSignal
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return `${url.pathname}${url.search}`
}

/** 发一个 JSON 请求；非 2xx 响应抛 `ApiError`。204/空响应体返回 `undefined`。 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers: options.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  })

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response))
  }

  if (response.status === 204) {
    return undefined as T
  }
  const text = await response.text()
  if (!text) {
    return undefined as T
  }
  return JSON.parse(text) as T
}

/** 读原始文件内容（`GET /projects/{id}/files/{path}`）：不假定是 JSON。 */
export async function requestText(
  path: string,
  options: Omit<RequestOptions, 'body'> = {},
): Promise<string> {
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    signal: options.signal,
  })
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response))
  }
  return response.text()
}

export { BASE_URL }
