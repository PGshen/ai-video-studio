/**
 * 风格预设编辑器的纯逻辑（计划 M5 T11）：草稿、校验、文件增删改、草稿 ↔ 请求体。
 * 校验规则和后端 `db/repo/style_presets.py::validate_style_preset` 保持一致（后端是最终
 * 裁判，这里让使用者保存前就看到问题，错误文案也一样，点名到文件）。
 *
 * 一套风格是 skill 形态的目录（ADR 0011）：入口 `STYLE.md`（`content`）+ `references/*.md`
 * + `exemplars/*.json|md`。
 */

import type { EditorLanguage } from '@/components/codeEditorLanguage'
import type {
  StyleFile,
  StylePresetCreate,
  StylePresetOut,
  StylePresetPatch,
  StylePresetSummaryOut,
} from '@/types/api'

export const MAX_FILE_CHARS = 200_000
export const MAX_FILES_PER_DIR = 30
export const MAX_NAME_CHARS = 100
export const MAX_FILE_NAME_CHARS = 80

export type StyleDir = 'references' | 'exemplars'

const DIR_SUFFIXES: Record<StyleDir, readonly string[]> = {
  references: ['.md'],
  exemplars: ['.json', '.md'],
}

const FILE_NAME = /^[\p{L}\p{N}_.-]+$/u
const ENTRY_REFERENCE = /(?<![\p{L}\p{N}_])(references|exemplars)\/([\p{L}\p{N}_.-]+)/gu
const FRONTMATTER = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/

export interface StyleDraft {
  name: string
  category: string
  description: string
  content: string
  references: StyleFile[]
  exemplars: StyleFile[]
}

const ENTRY_TEMPLATE = `---
name: 新风格
description: 一句话说明这套风格是什么
---

# 新风格

在这里写风格的概述，以及每个文件什么时候读。例如：

| 文件 | 内容 | 什么时候读 |
|---|---|---|
`

export function emptyDraft(): StyleDraft {
  return {
    name: '',
    category: '未分类',
    description: '',
    content: ENTRY_TEMPLATE,
    references: [],
    exemplars: [],
  }
}

export function draftFromPreset(preset: StylePresetOut): StyleDraft {
  return {
    name: preset.name,
    category: preset.category,
    description: preset.description ?? '',
    content: preset.content,
    references: preset.references.map((f) => ({ ...f })),
    exemplars: preset.exemplars.map((f) => ({ ...f })),
  }
}

/** 解析 `STYLE.md` 开头 `---` 块里的 `key: value` 行；没有完整的块返回 `null`。 */
export function parseFrontmatter(content: string): Record<string, string> | null {
  const match = FRONTMATTER.exec(content)
  if (!match) return null
  const result: Record<string, string> = {}
  for (const line of (match[1] ?? '').split(/\r?\n/)) {
    const colon = line.indexOf(':')
    if (colon < 0) continue
    const key = line.slice(0, colon).trim()
    if (!key) continue
    let value = line.slice(colon + 1).trim()
    if (value.length >= 2 && value[0] === value[value.length - 1] && '"\''.includes(value[0]!)) {
      const quote = value[0]
      value = value.slice(1, -1)
      // YAML 双引号字符串里 \" 和 \\ 是转义
      if (quote === '"') value = value.replace(/\\(["\\])/g, '$1')
    }
    result[key] = value
  }
  return result
}

export function isValidFileName(name: string): boolean {
  return (
    name.length > 0 &&
    name.length <= MAX_FILE_NAME_CHARS &&
    !name.startsWith('.') &&
    FILE_NAME.test(name)
  )
}

function validateFiles(dir: StyleDir, files: StyleFile[], errors: string[]): void {
  if (files.length > MAX_FILES_PER_DIR) {
    errors.push(`${dir}/ 最多 ${MAX_FILES_PER_DIR} 个文件，现在有 ${files.length} 个`)
  }
  const seen = new Set<string>()
  const suffixes = DIR_SUFFIXES[dir]
  for (const file of files) {
    const label = `${dir}/${file.name}`
    if (!isValidFileName(file.name)) {
      errors.push(`文件名不合法：'${label}'（只允许字母、数字、下划线、点和连字符，不能以点开头）`)
      continue
    }
    if (seen.has(file.name)) errors.push(`文件名重复：${label}`)
    seen.add(file.name)
    if (!suffixes.some((suffix) => file.name.endsWith(suffix))) {
      errors.push(`${label} 的扩展名只能是 ${suffixes.join(' / ')}`)
    }
    if (file.text.length > MAX_FILE_CHARS) errors.push(`${label} 过长（上限 ${MAX_FILE_CHARS} 字符）`)
    if (file.name.endsWith('.json')) {
      try {
        JSON.parse(file.text)
      } catch {
        errors.push(`${label} 不是合法的 JSON`)
      }
    }
  }
}

/** 返回中文错误列表，空数组表示合法。 */
export function validateDraft(draft: StyleDraft): string[] {
  const errors: string[] = []
  const name = draft.name.trim()
  if (!name) errors.push('名称不能为空')
  else if (name.length > MAX_NAME_CHARS) errors.push(`名称过长（上限 ${MAX_NAME_CHARS} 字）`)

  const front = parseFrontmatter(draft.content)
  if (front === null) {
    errors.push('STYLE.md 必须以 frontmatter 开头（--- 包起来的 name、description）')
  } else {
    for (const key of ['name', 'description']) {
      if (!(front[key] ?? '').trim()) errors.push(`STYLE.md 的 frontmatter 缺少非空的 ${key}`)
    }
  }
  if (draft.content.length > MAX_FILE_CHARS) errors.push(`STYLE.md 过长（上限 ${MAX_FILE_CHARS} 字符）`)

  validateFiles('references', draft.references, errors)
  validateFiles('exemplars', draft.exemplars, errors)

  const existing: Record<StyleDir, Set<string>> = {
    references: new Set(draft.references.map((f) => f.name)),
    exemplars: new Set(draft.exemplars.map((f) => f.name)),
  }
  const reported = new Set<string>()
  for (const match of draft.content.matchAll(ENTRY_REFERENCE)) {
    const dir = match[1] as StyleDir
    const fileName = match[2]!
    const path = `${dir}/${fileName}`
    if (!existing[dir].has(fileName) && !reported.has(path)) {
      reported.add(path)
      errors.push(`STYLE.md 引用了不存在的文件：${path}`)
    }
  }
  return errors
}

export function draftToCreate(draft: StyleDraft): StylePresetCreate {
  return {
    name: draft.name.trim(),
    category: draft.category.trim() || '未分类',
    description: draft.description.trim() || null,
    content: draft.content,
    references: draft.references,
    exemplars: draft.exemplars,
  }
}

function sameFiles(a: StyleFile[], b: StyleFile[]): boolean {
  return a.length === b.length && a.every((f, i) => f.name === b[i]!.name && f.text === b[i]!.text)
}

/** 只含改过的字段；列表字段整体替换。 */
export function draftToPatch(draft: StyleDraft, original: StylePresetOut): StylePresetPatch {
  const target = draftToCreate(draft)
  const patch: StylePresetPatch = {}
  if (target.name !== original.name) patch.name = target.name
  if (target.category !== original.category) patch.category = target.category
  if (target.description !== original.description) patch.description = target.description
  if (target.content !== original.content) patch.content = target.content
  if (!sameFiles(target.references, original.references)) patch.references = target.references
  if (!sameFiles(target.exemplars, original.exemplars)) patch.exemplars = target.exemplars
  return patch
}

/** 有没有未保存的修改；`original` 为 `null` 表示新建草稿，和空草稿比。 */
export function isDirty(draft: StyleDraft, original: StylePresetOut | null): boolean {
  if (original === null) {
    const blank = emptyDraft()
    return (
      draft.name !== blank.name ||
      draft.category !== blank.category ||
      draft.description !== blank.description ||
      draft.content !== blank.content ||
      draft.references.length > 0 ||
      draft.exemplars.length > 0
    )
  }
  return Object.keys(draftToPatch(draft, original)).length > 0
}

export function addFile(
  draft: StyleDraft,
  dir: StyleDir,
  rawName: string,
): { draft: StyleDraft; error: string | null } {
  const name = rawName.trim()
  if (!isValidFileName(name)) {
    return {
      draft,
      error: `文件名不合法：只允许字母、数字、下划线、点和连字符，不能以点开头（${MAX_FILE_NAME_CHARS} 字以内）`,
    }
  }
  const suffixes = DIR_SUFFIXES[dir]
  if (!suffixes.some((suffix) => name.endsWith(suffix))) {
    return { draft, error: `${dir}/ 下的文件扩展名只能是 ${suffixes.join(' / ')}` }
  }
  if (draft[dir].some((f) => f.name === name)) {
    return { draft, error: `${dir}/ 下已有同名文件：${name}` }
  }
  if (draft[dir].length >= MAX_FILES_PER_DIR) {
    return { draft, error: `${dir}/ 最多 ${MAX_FILES_PER_DIR} 个文件` }
  }
  const text = name.endsWith('.json') ? '{}\n' : ''
  return { draft: { ...draft, [dir]: [...draft[dir], { name, text }] }, error: null }
}

export function removeFile(draft: StyleDraft, dir: StyleDir, name: string): StyleDraft {
  return { ...draft, [dir]: draft[dir].filter((f) => f.name !== name) }
}

export function updateFileText(
  draft: StyleDraft,
  dir: StyleDir,
  name: string,
  text: string,
): StyleDraft {
  return { ...draft, [dir]: draft[dir].map((f) => (f.name === name ? { ...f, text } : f)) }
}

export function fileLanguage(name: string): EditorLanguage {
  if (name.endsWith('.json')) return 'json'
  if (name.endsWith('.md')) return 'markdown'
  return 'text'
}

export interface StyleGroup {
  category: string
  items: StylePresetSummaryOut[]
}

/** 按分类分组（分类、组内名称都按顺序，空分类归到「未分类」）。 */
export function groupByCategory(presets: StylePresetSummaryOut[]): StyleGroup[] {
  const groups = new Map<string, StylePresetSummaryOut[]>()
  for (const preset of presets) {
    const category = preset.category.trim() || '未分类'
    groups.set(category, [...(groups.get(category) ?? []), preset])
  }
  return [...groups.entries()]
    .map(([category, items]) => ({
      category,
      items: [...items].sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN')),
    }))
    .sort((a, b) => {
      // 「未分类」放最后，其余按名称
      if (a.category === '未分类') return 1
      if (b.category === '未分类') return -1
      return a.category.localeCompare(b.category, 'zh-Hans-CN')
    })
}
