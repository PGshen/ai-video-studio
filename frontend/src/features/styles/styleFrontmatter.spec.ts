import { describe, expect, it } from 'vitest'
import { parseFrontmatter, readStyleMeta, stripFrontmatter, updateFrontmatter } from './styleFrontmatter'

const ENTRY = `---
name: 暖纸双色
description: 暖色纸张质感的双色风格
category: 概念传记
---

# 暖纸双色

先读 \`references/color.md\`。
`

describe('parseFrontmatter', () => {
  it('读出 name、description、category', () => {
    expect(parseFrontmatter(ENTRY)).toEqual({
      name: '暖纸双色',
      description: '暖色纸张质感的双色风格',
      category: '概念传记',
    })
  })

  it.each([`"带: 冒号"`, `'带: 冒号'`])('去掉成对的引号：%s', (value) => {
    expect(parseFrontmatter(`---\nname: ${value}\n---\n`)).toEqual({ name: '带: 冒号' })
  })

  it('双引号里的 \\" 和 \\\\ 是转义', () => {
    expect(parseFrontmatter('---\nname: "带\\"引号\\"和\\\\反斜杠"\n---\n')).toEqual({
      name: '带"引号"和\\反斜杠',
    })
  })

  it.each(['# 没有 frontmatter\n', '---\nname: x\n', ''])('没有完整的块时返回 null：%j', (content) => {
    expect(parseFrontmatter(content)).toBeNull()
  })
})

describe('readStyleMeta', () => {
  it('缺的字段是空字符串', () => {
    expect(readStyleMeta('---\nname: n\n---\n')).toEqual({ name: 'n', description: '', category: '' })
    expect(readStyleMeta('没有 frontmatter')).toEqual({ name: '', description: '', category: '' })
  })
})

describe('updateFrontmatter', () => {
  it('只改指定字段，其余内容原样保留', () => {
    const out = updateFrontmatter(ENTRY, { name: '新名字' })
    expect(readStyleMeta(out)).toEqual({
      name: '新名字',
      description: '暖色纸张质感的双色风格',
      category: '概念传记',
    })
    expect(out.endsWith(ENTRY.split('---\n')[2]!)).toBe(true)
  })

  it('缺的字段补在块的末尾', () => {
    const out = updateFrontmatter('---\nname: n\ndescription: d\n---\n正文\n', { category: '科普' })
    expect(readStyleMeta(out).category).toBe('科普')
    expect(out.endsWith('---\n正文\n')).toBe(true)
  })

  it('没有 frontmatter 时在开头补一个', () => {
    const out = updateFrontmatter('# 标题\n', { name: 'n', description: 'd' })
    expect(readStyleMeta(out)).toEqual({ name: 'n', description: 'd', category: '' })
    expect(out.endsWith('# 标题\n')).toBe(true)
  })

  it.each(['带: 冒号', 'say "hi"', 'back\\slash', ' 首尾空格 ', '#井号', ''])(
    '值 %j 写进去再读出来不变',
    (value) => {
      expect(readStyleMeta(updateFrontmatter('---\nname: n\n---\n', { name: value })).name).toBe(
        value,
      )
    },
  )

  it('多行的值折成一行', () => {
    const out = updateFrontmatter('---\nname: n\n---\n', { description: '第一行\n第二行' })
    expect(readStyleMeta(out).description).toBe('第一行 第二行')
  })

  it('与后端 set_frontmatter_fields 的格式一致：值需要引号时用双引号并转义', () => {
    const out = updateFrontmatter('---\nname: n\n---\n', { name: 'say "hi"' })
    expect(out).toContain('name: "say \\"hi\\""')
  })
})

describe('stripFrontmatter', () => {
  it('去掉开头的 frontmatter 块，保留正文（含开头的空行之后的内容）', () => {
    expect(stripFrontmatter(ENTRY).startsWith('\n# 暖纸双色')).toBe(true)
    expect(stripFrontmatter(ENTRY)).not.toContain('description:')
  })

  it('没有 frontmatter 时原样返回；正文里的 --- 分隔线不受影响', () => {
    expect(stripFrontmatter('# 标题\n\n---\n\n正文\n')).toBe('# 标题\n\n---\n\n正文\n')
    expect(stripFrontmatter('')).toBe('')
  })
})
