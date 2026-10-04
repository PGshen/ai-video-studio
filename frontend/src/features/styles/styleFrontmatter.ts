/**
 * `STYLE.md` frontmatter 的读写（名称、简介、分类都在这里，ADR 0019）。
 * 解析和格式规则与后端 `studio.styles.validate.parse_frontmatter`/`set_frontmatter_fields`
 * 保持一致：`key: value` 行、成对引号、双引号里 `\"` 和 `\\` 是转义。
 */

export interface StyleMeta {
  name: string
  description: string
  category: string
}

const FRONTMATTER = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/

/** 开头 `---` 块里的 `key: value`；没有完整的块时返回 `null`。 */
export function parseFrontmatter(content: string): Record<string, string> | null {
  const match = FRONTMATTER.exec(content)
  if (match === null) return null
  const result: Record<string, string> = {}
  for (const line of (match[1] ?? '').split(/\r?\n/)) {
    const index = line.indexOf(':')
    if (index < 0) continue
    const key = line.slice(0, index).trim()
    if (key === '') continue
    let value = line.slice(index + 1).trim()
    const quote = value[0]
    if (value.length >= 2 && (quote === '"' || quote === "'") && value.endsWith(quote)) {
      value = value.slice(1, -1)
      if (quote === '"') value = value.replace(/\\(["\\])/g, '$1')
    }
    result[key] = value
  }
  return result
}

export function readStyleMeta(content: string): StyleMeta {
  const meta = parseFrontmatter(content) ?? {}
  return {
    name: meta['name'] ?? '',
    description: meta['description'] ?? '',
    category: meta['category'] ?? '',
  }
}

function formatValue(raw: string): string {
  const value = raw.split(/\r?\n/).join(' ')
  const needsQuotes = value === '' || value !== value.trim() || /[:#"'\\]/.test(value)
  return needsQuotes ? `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"` : value
}

/** 改写（或追加）指定字段，其余内容原样保留；没有 frontmatter 时在开头补一个。 */
export function updateFrontmatter(content: string, patch: Partial<StyleMeta>): string {
  const match = FRONTMATTER.exec(content)
  const lines = match === null ? [] : (match[1] ?? '').split(/\r?\n/)
  const rest = match === null ? content : content.slice(match[0].length)
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue
    const line = `${key}: ${formatValue(value)}`
    const index = lines.findIndex(
      (existing) => existing.includes(':') && existing.split(':')[0]!.trim() === key,
    )
    if (index >= 0) lines[index] = line
    else lines.push(line)
  }
  return `---\n${lines.join('\n')}\n---\n${rest}`
}
