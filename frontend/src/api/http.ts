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
  /** 数组值编码成同名重复参数（`?scene_id=a&scene_id=b`），匹配 FastAPI 的 `list[str]` query 参数。 */
  query?: Record<string, string | number | boolean | string[] | null | undefined>
  body?: unknown
  signal?: AbortSignal
}

/**
 * 对一段动态拼进 URL 路径的值做百分号编码（项目 id、阶段名、快照 id 等）。
 * `endpoints.ts` 在每一处把 id/名字拼进路径模板时都要过一遍这个函数，
 * 否则名字里出现 `#`（被当成 fragment 起点）、`?`（被当成 query 起点）、
 * 空格等字符会让 `new URL()` 解析出错误的路径（审查发现，T12）。
 */
export function encodePathSegment(segment: string): string {
  return encodeURIComponent(segment)
}

/**
 * 编码一个**文件路径**（工作区里的相对路径，比如 `topic/fake-note.md`）：
 * 按 `/` 切开逐段编码再拼回去，保留路径分隔符本身，只编码每一段里的特殊
 * 字符。不能直接对整个路径调用 `encodePathSegment`（会把 `/` 也编码掉，
 * 破坏目录结构）。
 */
export function encodeFilePath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/')
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined) continue
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, item)
      } else {
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
