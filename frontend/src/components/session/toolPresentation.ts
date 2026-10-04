/**
 * 工具调用的展示归类（设计 §5）：把两个运行时的工具名/参数归一成「渲染种类 + 一行摘要」。
 * Claude 原生工具（`Read`/`Write`/`Edit`/`Glob`/`Grep`/`Bash`/`WebSearch`/`WebFetch`）和
 * OpenAI·自建工具（`read_file`/`write_file`/`edit_file`/`apply_patch`/`list_files`/`shell`/
 * `web_search`/`fetch_url`）在这里对齐；参数缺失或类型不符时一律退回 `generic`，不抛错。
 */
import type { ToolCallItem } from '@/composables/useSessionStream'

export type ToolKind =
  | 'read'
  | 'write'
  | 'glob'
  | 'grep'
  | 'bash'
  | 'web-search'
  | 'web-fetch'
  | 'generic'

export interface ToolView {
  kind: ToolKind
  /** 折叠行里的类型名，例如「读取」。generic 时是工具原名。 */
  label: string
  /** 折叠行里 `·` 后面的一句摘要。 */
  summary: string
  /** 读写类工具的工作区相对路径。 */
  path?: string
}

export type ToolStatus = 'running' | 'done' | 'error' | 'interrupted'

const GENERIC_SUMMARY_MAX = 80
const WORKSPACE_SEGMENT = /\/(?:projects|scratch|style-drafts)\/[^/]+\/(.+)$/

export function relativizePath(path: string, workdirPrefix?: string): string {
  if (workdirPrefix) {
    const prefix = workdirPrefix.endsWith('/') ? workdirPrefix : `${workdirPrefix}/`
    if (path.startsWith(prefix)) return path.slice(prefix.length)
  }
  const match = WORKSPACE_SEGMENT.exec(path)
  return match ? match[1]! : path
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined
}

function firstLine(text: string): string {
  return (
    text
      .split('\n')
      .map((line) => line.trim())
      .find((line) => line !== '') ?? ''
  )
}

function generic(item: ToolCallItem): ToolView {
  let summary = ''
  for (const value of Object.values(item.args)) {
    const text = str(value)
    if (text !== undefined) {
      summary = firstLine(text)
      break
    }
  }
  if (summary.length > GENERIC_SUMMARY_MAX) summary = `${summary.slice(0, GENERIC_SUMMARY_MAX)}…`
  return { kind: 'generic', label: item.name, summary }
}

function fileView(
  item: ToolCallItem,
  kind: 'read' | 'write',
  label: string,
  key: string[],
  workdirPrefix?: string,
): ToolView {
  const raw = key.map((name) => str(item.args[name])).find((value) => value !== undefined)
  if (raw === undefined) return generic(item)
  const path = relativizePath(raw, workdirPrefix)
  return { kind, label, summary: path, path }
}

function bashView(item: ToolCallItem): ToolView {
  const { args } = item
  const description = str(args.description)
  const command = str(args.command)
  if (description !== undefined && command !== undefined) {
    return { kind: 'bash', label: 'Bash', summary: description.trim() }
  }
  if (command !== undefined) return { kind: 'bash', label: 'Bash', summary: firstLine(command) }
  const commands = args.commands
  if (Array.isArray(commands)) {
    const list = commands.filter((c): c is string => typeof c === 'string' && c.trim() !== '')
    if (list.length > 0) {
      const head = firstLine(list[0]!)
      return {
        kind: 'bash',
        label: 'Bash',
        summary: list.length > 1 ? `${head} 等 ${list.length} 条` : head,
      }
    }
  }
  return generic(item)
}

function fetchSummary(url: string): string {
  try {
    const parsed = new URL(url)
    return parsed.pathname === '/' ? parsed.host : `${parsed.host}${parsed.pathname}`
  } catch {
    return url
  }
}

export function describeTool(item: ToolCallItem, workdirPrefix?: string): ToolView {
  const { args } = item
  switch (item.name) {
    case 'Read':
    case 'read_file':
      return fileView(item, 'read', '读取', ['file_path', 'path'], workdirPrefix)
    case 'Write':
    case 'write_file':
      return fileView(item, 'write', '写入', ['file_path', 'path'], workdirPrefix)
    case 'Edit':
    case 'MultiEdit':
    case 'edit_file':
    case 'NotebookEdit':
      return fileView(item, 'write', '编辑', ['file_path', 'path', 'notebook_path'], workdirPrefix)
    case 'apply_patch':
      return fileView(item, 'write', '补丁', ['path'], workdirPrefix)
    case 'Glob': {
      const pattern = str(args.pattern)
      return pattern === undefined
        ? generic(item)
        : { kind: 'glob', label: 'Glob', summary: pattern }
    }
    case 'list_files': {
      const dir = args.dir
      if (dir !== undefined && typeof dir !== 'string') return generic(item)
      const summary = dir && dir.trim() !== '' ? relativizePath(dir, workdirPrefix) : '工作区'
      return { kind: 'glob', label: '列目录', summary }
    }
    case 'Grep': {
      const pattern = str(args.pattern)
      return pattern === undefined
        ? generic(item)
        : { kind: 'grep', label: 'Grep', summary: pattern }
    }
    case 'Bash':
    case 'shell':
      return bashView(item)
    case 'WebSearch':
    case 'web_search': {
      const query = str(args.query)
      return query === undefined
        ? generic(item)
        : { kind: 'web-search', label: '联网搜索', summary: query }
    }
    case 'WebFetch':
    case 'fetch_url': {
      const url = str(args.url)
      return url === undefined
        ? generic(item)
        : { kind: 'web-fetch', label: '读取网页', summary: fetchSummary(url.trim()) }
    }
    default:
      return generic(item)
  }
}

/** 没有结果且所在 turn 已经结束（取消/崩溃/预算耗尽）→ `interrupted`，不再一直转圈。 */
export function toolStatus(item: ToolCallItem, turnEnded: boolean): ToolStatus {
  if (item.result) return item.result.isError ? 'error' : 'done'
  return turnEnded ? 'interrupted' : 'running'
}
