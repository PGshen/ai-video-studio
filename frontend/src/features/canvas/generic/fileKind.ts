/**
 * 按扩展名决定 CodeEditor 语言包、以及是不是"文本文件"（任务简报 T14，
 * 控制者裁定 1/4）：非文本扩展名一律当二进制处理，画布里显示"二进制文件，
 * 不可编辑"占位，不请求 `GET /files/{path}` 把整段字节流当字符串用（那
 * 会把图片/视频这类文件搞乱，浏览器 `fetch().text()` 对二进制内容也不一定
 * 安全解码）。这是一份白名单而不是黑名单：新出现的、没见过的扩展名默认
 * 当二进制，宁可少编辑一些文件，也不要把真正的二进制文件当文本读坏。
 *
 * `EditorLanguage` 类型本身定义在 `@/components/codeEditorLanguage`（T12
 * 决策记录 D36），这里重新导出，保持这个模块原有的对外接口不变。
 */
import type { EditorLanguage } from '@/components/codeEditorLanguage'

export type { EditorLanguage }

const LANGUAGE_BY_EXT: Record<string, EditorLanguage> = {
  md: 'markdown',
  markdown: 'markdown',
  json: 'json',
  py: 'python',
}

const TEXT_EXTENSIONS = new Set([
  'md',
  'markdown',
  'json',
  'py',
  'js',
  'svg',
  'txt',
  'yaml',
  'yml',
  'csv',
  'toml',
  'ini',
  'cfg',
])

function extensionOf(path: string): string {
  const name = path.split('/').pop() ?? path
  const dot = name.lastIndexOf('.')
  if (dot <= 0) return '' // 没有扩展名，或者是隐藏文件（`.gitignore` 这种没有"名字"部分）。
  return name.slice(dot + 1).toLowerCase()
}

export function isTextFile(path: string): boolean {
  return TEXT_EXTENSIONS.has(extensionOf(path))
}

export function editorLanguage(path: string): EditorLanguage {
  return LANGUAGE_BY_EXT[extensionOf(path)] ?? 'text'
}
