import { describe, expect, it } from 'vitest'
import type { StylePresetOut, StyleFile } from '@/types/api'
import {
  MAX_FILES_PER_DIR,
  addFile,
  draftFromPreset,
  draftToCreate,
  draftToPatch,
  emptyDraft,
  fileLanguage,
  groupByCategory,
  isDirty,
  isValidFileName,
  parseFrontmatter,
  removeFile,
  updateFileText,
  validateDraft,
  type StyleDraft,
} from './styleDraft'

const ENTRY = `---
name: 暖纸双色
description: 暖色纸张质感的双色风格
---

先读 \`references/color-scheme.md\`，写叙事前再看 \`exemplars/exemplar-1.json\`。
`

function draft(overrides: Partial<StyleDraft> = {}): StyleDraft {
  return {
    name: '暖纸双色',
    category: '概念传记',
    description: '',
    content: ENTRY,
    references: [{ name: 'color-scheme.md', text: '主色：暖白' }],
    exemplars: [{ name: 'exemplar-1.json', text: '{}' }],
    ...overrides,
  }
}

function preset(overrides: Partial<StylePresetOut> = {}): StylePresetOut {
  return {
    id: 'p1',
    name: '暖纸双色',
    category: '概念传记',
    description: '暖色纸张质感的双色风格',
    content: ENTRY,
    references: [{ name: 'color-scheme.md', text: '主色：暖白' }],
    exemplars: [{ name: 'exemplar-1.json', text: '{}' }],
    is_default: false,
    created_at: '2026-09-30T00:00:00Z',
    ...overrides,
  }
}

describe('parseFrontmatter（与后端 parse_frontmatter 一致）', () => {
  it('解析 name 和 description', () => {
    expect(parseFrontmatter(ENTRY)).toEqual({
      name: '暖纸双色',
      description: '暖色纸张质感的双色风格',
    })
  })

  it.each(['# 没有 frontmatter\n', '---\nname: x\n', ''])('没有闭合的块返回 null：%j', (content) => {
    expect(parseFrontmatter(content)).toBeNull()
  })

  it('去掉成对的引号，双引号里的 \\" 和 \\\\ 是转义', () => {
    expect(parseFrontmatter('---\nname: "带\\"引号\\"和\\\\反斜杠"\n---\n')).toEqual({
      name: '带"引号"和\\反斜杠',
    })
    expect(parseFrontmatter("---\nname: 'a: b'\n---\n")).toEqual({ name: 'a: b' })
  })
})

describe('isValidFileName', () => {
  it.each(['color-scheme.md', 'a_b.c.md', '中文名.md', 'x.json'])('合法：%s', (name) => {
    expect(isValidFileName(name)).toBe(true)
  })

  it.each(['', '../evil.md', 'a/b.md', '/abs.md', '..', '.hidden.md', 'a b.md', `${'x'.repeat(81)}.md`])(
    '不合法：%j',
    (name) => {
      expect(isValidFileName(name)).toBe(false)
    },
  )
})

describe('validateDraft（与后端 validate_style_preset 一致）', () => {
  it('合法草稿没有错误', () => {
    expect(validateDraft(draft())).toEqual([])
  })

  it('名称不能为空', () => {
    expect(validateDraft(draft({ name: '  ' }))[0]).toContain('名称')
  })

  it.each([
    ['# 没有 frontmatter', 'frontmatter'],
    ['---\ndescription: d\n---\n', 'name'],
    ['---\nname: n\n---\n', 'description'],
  ])('入口需要 name 和 description：%j', (content, needle) => {
    const errors = validateDraft(draft({ content, references: [], exemplars: [] }))
    expect(errors.some((e) => e.includes('STYLE.md') && e.includes(needle))).toBe(true)
  })

  it('文件名不合法、重名、扩展名错误各自点名', () => {
    const content = '---\nname: n\ndescription: d\n---\n'
    const errors = validateDraft(
      draft({
        content,
        references: [
          { name: '../x.md', text: '' },
          { name: 'a.md', text: '1' },
          { name: 'a.md', text: '2' },
          { name: 'b.json', text: '{}' },
        ],
        exemplars: [{ name: 'c.py', text: '' }],
      }),
    )
    expect(errors.some((e) => e.includes('../x.md') && e.includes('文件名'))).toBe(true)
    expect(errors.some((e) => e.includes('a.md') && e.includes('重复'))).toBe(true)
    expect(errors.some((e) => e.includes('b.json'))).toBe(true)
    expect(errors.some((e) => e.includes('c.py'))).toBe(true)
  })

  it('.json 金样本必须是合法 JSON', () => {
    const content = '---\nname: n\ndescription: d\n---\n'
    const errors = validateDraft(
      draft({ content, references: [], exemplars: [{ name: 'e.json', text: '{oops' }] }),
    )
    expect(errors.some((e) => e.includes('e.json') && e.includes('JSON'))).toBe(true)
  })

  it('入口引用了不存在的文件时点名', () => {
    const errors = validateDraft(draft({ references: [], exemplars: [{ name: 'exemplar-1.json', text: '{}' }] }))
    expect(errors).toEqual(['STYLE.md 引用了不存在的文件：references/color-scheme.md'])
  })

  it('只提到目录（没有文件名）不算引用', () => {
    const content = '---\nname: n\ndescription: d\n---\n详见 references/ 目录和 exemplars/*.json。'
    expect(validateDraft(draft({ content, references: [], exemplars: [] }))).toEqual([])
  })

  it('每个目录最多 30 个文件', () => {
    const many: StyleFile[] = Array.from({ length: MAX_FILES_PER_DIR + 1 }, (_, i) => ({
      name: `f${i}.md`,
      text: '',
    }))
    const content = '---\nname: n\ndescription: d\n---\n'
    expect(validateDraft(draft({ content, references: many, exemplars: [] })).some((e) => e.includes('最多'))).toBe(true)
  })
})

describe('草稿 ↔ 预设', () => {
  it('draftFromPreset 复制内容，description 为空时留空字符串', () => {
    const value = draftFromPreset(preset({ description: null }))
    expect(value.description).toBe('')
    expect(value.references).toEqual(preset().references)
  })

  it('draftToCreate 去空白，空 description 发 null', () => {
    const body = draftToCreate(draft({ name: ' 暖纸双色 ', category: ' 概念传记 ', description: '' }))
    expect(body.name).toBe('暖纸双色')
    expect(body.category).toBe('概念传记')
    expect(body.description).toBeNull()
  })

  it('没改任何东西补丁为空', () => {
    const original = preset()
    expect(draftToPatch(draftFromPreset(original), original)).toEqual({})
  })

  it('只包含改过的字段，列表整体替换', () => {
    const original = preset()
    const edited = {
      ...draftFromPreset(original),
      category: '新分类',
      references: [...original.references, { name: 'extra.md', text: 'x' }],
    }

    expect(draftToPatch(edited, original)).toEqual({
      category: '新分类',
      references: edited.references,
    })
  })

  it('isDirty 反映是否有未保存修改', () => {
    const original = preset()
    expect(isDirty(draftFromPreset(original), original)).toBe(false)
    expect(isDirty({ ...draftFromPreset(original), content: `${ENTRY}\n改` }, original)).toBe(true)
  })

  it('新建草稿（没有原预设）总是脏的当且仅当有内容改动', () => {
    expect(isDirty(emptyDraft(), null)).toBe(false)
    expect(isDirty({ ...emptyDraft(), name: '新的' }, null)).toBe(true)
  })
})

describe('emptyDraft', () => {
  it('入口带 frontmatter 模板，自己就通过入口检查（只差名称）', () => {
    const value = emptyDraft()
    expect(parseFrontmatter(value.content)).not.toBeNull()
    expect(validateDraft({ ...value, name: '新风格' }).filter((e) => e.includes('STYLE.md'))).toEqual([])
  })
})

describe('文件操作', () => {
  it('addFile 在对应目录加空文件，名字不合法或重名时拒绝', () => {
    const base = draft()
    const added = addFile(base, 'references', 'animation-style.md')
    expect(added.error).toBeNull()
    expect(added.draft.references.map((f) => f.name)).toEqual(['color-scheme.md', 'animation-style.md'])

    expect(addFile(base, 'references', '../x.md').error).toContain('文件名')
    expect(addFile(base, 'references', 'color-scheme.md').error).toContain('已有')
    expect(addFile(base, 'references', 'x.json').error).toContain('.md')
    expect(addFile(base, 'exemplars', 'x.py').error).toContain('.json')
  })

  it('removeFile 删掉指定文件，不影响其他目录', () => {
    const removed = removeFile(draft(), 'references', 'color-scheme.md')
    expect(removed.references).toEqual([])
    expect(removed.exemplars).toHaveLength(1)
  })

  it('updateFileText 只改指定文件', () => {
    const updated = updateFileText(draft(), 'exemplars', 'exemplar-1.json', '{"a":1}')
    expect(updated.exemplars[0]!.text).toBe('{"a":1}')
    expect(updated.references[0]!.text).toBe('主色：暖白')
  })
})

describe('fileLanguage', () => {
  it('按扩展名选编辑器语言', () => {
    expect(fileLanguage('x.json')).toBe('json')
    expect(fileLanguage('x.md')).toBe('markdown')
    expect(fileLanguage('x.txt')).toBe('text')
  })
})

describe('groupByCategory', () => {
  it('按分类分组，分类和组内名称都按顺序排，空分类归到「未分类」', () => {
    const groups = groupByCategory([
      { id: '1', name: 'b', category: 'B', description: null, reference_count: 0, exemplar_count: 0, is_default: false },
      { id: '2', name: 'a', category: 'B', description: null, reference_count: 0, exemplar_count: 0, is_default: false },
      { id: '3', name: 'c', category: 'A', description: null, reference_count: 0, exemplar_count: 0, is_default: false },
      { id: '4', name: 'd', category: '', description: null, reference_count: 0, exemplar_count: 0, is_default: false },
    ])

    expect(groups.map((g) => g.category)).toEqual(['A', 'B', '未分类'])
    expect(groups[1]!.items.map((i) => i.name)).toEqual(['a', 'b'])
  })
})
