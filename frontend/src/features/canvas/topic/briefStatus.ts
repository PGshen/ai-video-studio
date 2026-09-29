/**
 * 选题画布的纯逻辑（计划 M4 T11）：简报检查结果 → 提示条状态；从文件树里取笔记列表。
 *
 * 检查本身在后端（`GET /projects/{id}/topic/check`，和 `check_brief` 工具同一份逻辑），
 * 这里只负责把结果翻成界面状态。有错误时后端 `finalize` 会拒绝（409，计划 D4 已改为强制），
 * 「定稿」按钮不在这里禁用（`StageNav` 在 `features/workbench`），被拒时导航条显示原因。
 */

import type { TopicCheckOut } from '@/types/api'

export const BRIEF_PATH = 'topic/brief.md'
const NOTES_PREFIX = 'topic/notes/'
const TEXT_EXTENSIONS = ['.md', '.markdown', '.txt']

export interface BriefStatus {
  level: 'unknown' | 'errors' | 'warnings' | 'ok'
  headline: string
  errors: string[]
  warnings: string[]
}

export function computeBriefStatus(check: TopicCheckOut | undefined): BriefStatus {
  if (check === undefined) {
    return { level: 'unknown', headline: '正在检查简报…', errors: [], warnings: [] }
  }
  const { errors, warnings } = check
  if (errors.length > 0) {
    return {
      level: 'errors',
      headline: `不能定稿：简报有 ${errors.length} 个错误`,
      errors,
      warnings,
    }
  }
  if (warnings.length > 0) {
    return {
      level: 'warnings',
      headline: `可以定稿（有 ${warnings.length} 条警告，不阻止定稿）`,
      errors,
      warnings,
    }
  }
  return { level: 'ok', headline: '可以定稿：简报结构检查通过', errors, warnings }
}

export interface NoteFile {
  path: string
  /** 去掉 `topic/notes/` 前缀后的相对路径。 */
  label: string
}

/** `topic/notes/` 下的文本笔记（含子目录），按路径排序；`upstream/` 等其他目录不算。 */
export function noteFiles(paths: readonly string[]): NoteFile[] {
  return paths
    .filter(
      (path) =>
        path.startsWith(NOTES_PREFIX) &&
        TEXT_EXTENSIONS.some((ext) => path.toLowerCase().endsWith(ext)),
    )
    .sort()
    .map((path) => ({ path, label: path.slice(NOTES_PREFIX.length) }))
}
