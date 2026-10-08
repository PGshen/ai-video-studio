import { describe, expect, it } from 'vitest'
import type { StyleSummaryOut } from '@/types/api'
import {
  initialStyleId,
  selectableStyles,
  styleIdForRequest,
  styleOptionLabel,
  styleSelectOptions,
} from './styleChoice'

function preset(overrides: Partial<StyleSummaryOut>): StyleSummaryOut {
  return {
    id: 'p1',
    name: '暖纸双色',
    category: '概念传记',
    description: '暖色纸张质感',
    reference_count: 3,
    exemplar_count: 1,
    is_default: false,
    has_draft: false,
    is_new: false,
    cover: null,
    modified_at: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

describe('initialStyleId', () => {
  it('有默认风格时预选它', () => {
    const list = [preset({ id: 'a' }), preset({ id: 'b', is_default: true })]
    expect(initialStyleId(list)).toBe('b')
  })

  it('没有默认风格时不预选（空字符串 = 不指定）', () => {
    expect(initialStyleId([preset({ id: 'a' })])).toBe('')
  })

  it('风格库为空时也是空字符串', () => {
    expect(initialStyleId([])).toBe('')
  })
})

describe('styleSelectOptions', () => {
  it('第一项是「不指定」，之后是各预设，默认的带标记', () => {
    const options = styleSelectOptions([
      preset({ id: 'a', name: 'A' }),
      preset({ id: 'b', name: 'B', is_default: true }),
    ])
    expect(options.map((o) => o.value)).toEqual(['', 'a', 'b'])
    expect(options[0]!.label).toContain('不指定')
    expect(options[2]!.label).toContain('默认')
    expect(options[1]!.label).not.toContain('默认')
  })
})

describe('styleOptionLabel', () => {
  it('显示名称，没有分类以外的信息时不多写', () => {
    expect(styleOptionLabel(preset({ name: 'X' }))).toBe('X')
    expect(styleOptionLabel(preset({ name: 'X', is_default: true }))).toBe('X（默认）')
  })
})

describe('styleIdForRequest', () => {
  it('空字符串不发（让服务端用默认风格或占位），其他原样发', () => {
    expect(styleIdForRequest('')).toBeUndefined()
    expect(styleIdForRequest('abc')).toBe('abc')
  })
})

describe('从未保存的新风格不能用来创建项目（后端只认已保存的风格，选了会 404）', () => {
  it('选项里不出现 is_new 的风格', () => {
    const list = [preset({ id: 'a' }), preset({ id: 'n', name: '新草稿', is_new: true, has_draft: true })]
    expect(styleSelectOptions(list).map((o) => o.value)).toEqual(['', 'a'])
    expect(selectableStyles(list).map((p) => p.id)).toEqual(['a'])
  })

  it('只有未保存的新风格时等于风格库为空', () => {
    expect(selectableStyles([preset({ id: 'n', is_new: true })])).toEqual([])
  })
})
