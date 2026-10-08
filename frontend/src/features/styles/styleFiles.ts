/** 风格目录里文件的分组和文件名检查（纯逻辑；规则与后端 `studio.styles.validate` 一致）。 */
import { BASE_URL, encodePathSegment } from '@/api/http'

export type StyleDirectory = 'references' | 'exemplars'

export const ENTRY_FILE = 'STYLE.md'
const MAX_FILE_NAME_CHARS = 80
const NAME_PATTERN = /^[\p{L}\p{N}_.-]+$/u
const SUFFIXES: Record<StyleDirectory, readonly string[]> = {
  references: ['.md'],
  exemplars: ['.json', '.md'],
}

export interface FileGroups {
  hasEntry: boolean
  references: string[]
  exemplars: string[]
}

export function groupFiles(files: readonly string[]): FileGroups {
  return {
    hasEntry: files.includes(ENTRY_FILE),
    references: files.filter((f) => f.startsWith('references/')),
    exemplars: files.filter((f) => f.startsWith('exemplars/')),
  }
}

/** 新文件名的问题（中文说明）；合法返回 `null`。`existing` 是草稿里已有的全部路径。 */
export function fileNameProblem(
  directory: StyleDirectory,
  rawName: string,
  existing: readonly string[],
): string | null {
  const name = rawName.trim()
  if (name === '') return '文件名不能为空'
  if (name.length > MAX_FILE_NAME_CHARS) return `文件名最多 ${MAX_FILE_NAME_CHARS} 个字符`
  if (name.startsWith('.') || !NAME_PATTERN.test(name)) {
    return '文件名只能包含字母、数字、下划线、点和连字符，不能以点开头'
  }
  const suffixes = SUFFIXES[directory]
  if (!suffixes.some((suffix) => name.endsWith(suffix))) {
    return `${directory}/ 下的文件扩展名只能是 ${suffixes.join(' 或 ')}`
  }
  if (existing.includes(`${directory}/${name}`)) return `${directory}/ 下已有同名文件`
  return null
}

/** 代码编辑器的语言：`.json` 用 json，其余（`STYLE.md`、引用文件、`.md` 金样本）用 markdown。 */
export function languageOf(path: string): 'json' | 'markdown' {
  return path.endsWith('.json') ? 'json' : 'markdown'
}

/** 一张截图的图片地址；`draft` 为真时取草稿里的（编辑态、从未保存的新风格），否则取正式版本。 */
export function screenshotUrl(styleId: string, name: string, options: { draft: boolean }): string {
  const base = `${BASE_URL}/styles/${encodePathSegment(styleId)}`
  return `${base}${options.draft ? '/draft' : ''}/screenshots/${encodePathSegment(name)}`
}
