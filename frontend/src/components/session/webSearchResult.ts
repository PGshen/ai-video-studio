/**
 * 联网搜索结果解析（设计 §5）。两种来源的文本形态不同：
 * - 自建 `web_search`：`搜索「q」，共 N 条结果：` 后跟编号条目（标题 / 缩进的 URL /
 *   `发布时间：` / 摘要，见 `stages/common/web_tools.py`）；
 * - Claude 原生 `WebSearch`：`Web search results for query: "q"` 后跟 `Links: [JSON 数组]`。
 * 无法识别时返回 `null`，调用方回退显示原始文本。
 */

export interface WebSearchHit {
  title: string
  url: string
  published?: string
  snippet?: string
}

export interface WebSearchResult {
  query?: string
  hits: WebSearchHit[]
}

const CUSTOM_HEADER = /^搜索「(.*)」，共 \d+ 条结果：\s*$/
const CUSTOM_EMPTY = /^搜索「(.*)」没有找到结果/
const NATIVE_HEADER = /^Web search results for query: "(.*)"\s*$/
const HIT_START = /^\d+\. (.+)$/
const HTTP_URL = /^https?:\/\/\S+$/
const PUBLISHED = /^发布时间：(.+)$/

function parseCustom(lines: string[]): WebSearchResult | null {
  for (const line of lines) {
    const empty = CUSTOM_EMPTY.exec(line)
    if (empty) return { query: empty[1], hits: [] }
  }
  const headerIndex = lines.findIndex((line) => CUSTOM_HEADER.test(line))
  if (headerIndex === -1) return null
  const query = CUSTOM_HEADER.exec(lines[headerIndex]!)![1]

  type Draft = { title: string; url?: string; published?: string; snippet: string[] }
  const drafts: Draft[] = []
  for (const line of lines.slice(headerIndex + 1)) {
    const start = HIT_START.exec(line)
    if (start) {
      drafts.push({ title: start[1]!.trim(), snippet: [] })
      continue
    }
    const draft = drafts.at(-1)
    if (!draft || !/^\s+\S/.test(line)) continue
    const body = line.trim()
    const published = PUBLISHED.exec(body)
    if (draft.url === undefined && HTTP_URL.test(body)) draft.url = body
    else if (published) draft.published = published[1]!.trim()
    else draft.snippet.push(body)
  }

  const hits: WebSearchHit[] = []
  for (const draft of drafts) {
    if (draft.url === undefined) continue
    const hit: WebSearchHit = { title: draft.title, url: draft.url }
    if (draft.published) hit.published = draft.published
    if (draft.snippet.length > 0) hit.snippet = draft.snippet.join(' ')
    hits.push(hit)
  }
  return hits.length > 0 ? { query, hits } : null
}

/** 从 `start`（指向 `[`）扫到配对的 `]`，识别字符串与转义；找不到返回 -1。 */
function matchingBracket(text: string, start: number): number {
  let depth = 0
  let inString = false
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i]!
    if (inString) {
      if (ch === '\\') i += 1
      else if (ch === '"') inString = false
    } else if (ch === '"') inString = true
    else if (ch === '[') depth += 1
    else if (ch === ']') {
      depth -= 1
      if (depth === 0) return i
    }
  }
  return -1
}

function parseNative(text: string, lines: string[]): WebSearchResult | null {
  const header = lines.map((line) => NATIVE_HEADER.exec(line)).find((m) => m !== null)
  if (!header) return null
  const linksAt = text.indexOf('Links:')
  if (linksAt === -1) return null
  const open = text.indexOf('[', linksAt)
  if (open === -1) return null
  const close = matchingBracket(text, open)
  if (close === -1) return null
  let raw: unknown
  try {
    raw = JSON.parse(text.slice(open, close + 1))
  } catch {
    return null
  }
  if (!Array.isArray(raw)) return null
  const hits: WebSearchHit[] = []
  for (const entry of raw) {
    if (typeof entry !== 'object' || entry === null) continue
    const { title, url } = entry as { title?: unknown; url?: unknown }
    if (typeof url !== 'string' || url === '') continue
    hits.push({ title: typeof title === 'string' && title !== '' ? title : url, url })
  }
  return { query: header[1], hits }
}

export function parseWebSearch(text: string): WebSearchResult | null {
  if (text.trim() === '') return null
  const lines = text.split('\n')
  return parseCustom(lines) ?? parseNative(text, lines)
}
