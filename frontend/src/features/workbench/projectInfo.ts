/**
 * 项目「信息」对话框的纯逻辑：找关联选题、读工作区 `style/STYLE.md` 的头部、把风格文件分组。
 * 项目创建时风格是被复制进工作区的，没有记录来源预设 id，所以这里只能展示工作区里的那份副本。
 */

import type { FileEntry, IdeaOut } from '@/types/api'

export function findProjectIdea(
  ideas: readonly IdeaOut[] | undefined,
  projectId: string,
): IdeaOut | null {
  return ideas?.find((idea) => idea.project_id === projectId) ?? null
}

export interface StyleHeader {
  name: string | null
  description: string | null
}

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---/

/** 读 `STYLE.md` 开头 frontmatter 里的 name / description（后端 `parse_frontmatter` 的前端版，只取这两个字段）。 */
export function parseStyleHeader(content: string | undefined): StyleHeader {
  const header: StyleHeader = { name: null, description: null }
  const block = content === undefined ? null : FRONTMATTER.exec(content)
  if (block === null) return header
  for (const line of block[1].split(/\r?\n/)) {
    const [rawKey, ...rest] = line.split(':')
    const key = rawKey.trim()
    if (key !== 'name' && key !== 'description') continue
    let value = rest.join(':').trim()
    if (value.length >= 2 && value[0] === value.at(-1) && '"\''.includes(value[0])) {
      value = value.slice(1, -1)
    }
    header[key] = value === '' ? null : value
  }
  return header
}

export interface StyleFileGroups {
  references: string[]
  exemplars: string[]
}

export function styleFileGroups(files: readonly FileEntry[] | undefined): StyleFileGroups {
  const groups: StyleFileGroups = { references: [], exemplars: [] }
  for (const { path } of files ?? []) {
    if (path.startsWith('style/references/')) groups.references.push(path.slice('style/references/'.length))
    else if (path.startsWith('style/exemplars/')) groups.exemplars.push(path.slice('style/exemplars/'.length))
  }
  return groups
}
