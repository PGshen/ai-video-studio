import { describe, expect, it } from 'vitest'
import type { StyleSummaryOut } from '@/types/api'
import { allCategories, filterStyles, sortStyles } from './styleView'

function style(overrides: Partial<StyleSummaryOut>): StyleSummaryOut {
  return {
    id: 's1',
    name: '暖纸双色',
    category: '概念传记',
    description: '暖色纸张质感的双色风格',
    reference_count: 3,
    exemplar_count: 1,
    is_default: false,
    has_draft: false,
    modified_at: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

const NO_FILTER = { keyword: '', category: null, onlyDefault: false }

describe('filterStyles', () => {
  const list = [
    style({ id: 'a', name: '暖纸双色', category: '概念传记' }),
    style({ id: 'b', name: '冷白学术图解', category: '科普', description: '紫青语义配色' }),
    style({ id: 'c', name: 'Minimal Pop', category: '科普', is_default: true }),
  ]

  it('没有条件时原样返回', () => {
    expect(filterStyles(list, NO_FILTER).map((s) => s.id)).toEqual(['a', 'b', 'c'])
  })

  it('关键词匹配名称、简介和分类，忽略大小写和首尾空白', () => {
    expect(filterStyles(list, { ...NO_FILTER, keyword: ' 紫青 ' }).map((s) => s.id)).toEqual(['b'])
    expect(filterStyles(list, { ...NO_FILTER, keyword: 'minimal' }).map((s) => s.id)).toEqual(['c'])
    expect(filterStyles(list, { ...NO_FILTER, keyword: '概念' }).map((s) => s.id)).toEqual(['a'])
  })

  it('分类精确匹配', () => {
    expect(filterStyles(list, { ...NO_FILTER, category: '科普' }).map((s) => s.id)).toEqual([
      'b',
      'c',
    ])
  })

  it('仅看默认', () => {
    expect(filterStyles(list, { ...NO_FILTER, onlyDefault: true }).map((s) => s.id)).toEqual(['c'])
  })

  it('条件叠加；简介为空的风格也能被名称搜到', () => {
    const withNull = [...list, style({ id: 'd', name: '无简介', description: null })]
    expect(
      filterStyles(withNull, { keyword: '无简介', category: '概念传记', onlyDefault: false }).map(
        (s) => s.id,
      ),
    ).toEqual(['d'])
  })
})

describe('allCategories', () => {
  it('去重并排序', () => {
    const list = [style({ category: '科普' }), style({ category: '概念传记' }), style({ category: '科普' })]
    expect(allCategories(list)).toEqual(['概念传记', '科普'])
  })

  it('没有风格时为空', () => {
    expect(allCategories([])).toEqual([])
  })
})

describe('sortStyles', () => {
  it('默认风格在前，其余按最近修改倒序，同时间按名称', () => {
    const list = [
      style({ id: 'old', name: '丙', modified_at: '2026-09-01T00:00:00Z' }),
      style({ id: 'new-b', name: 'b', modified_at: '2026-10-03T00:00:00Z' }),
      style({ id: 'def', name: '默认', is_default: true, modified_at: '2026-08-01T00:00:00Z' }),
      style({ id: 'new-a', name: 'a', modified_at: '2026-10-03T00:00:00Z' }),
    ]
    expect(sortStyles(list).map((s) => s.id)).toEqual(['def', 'new-a', 'new-b', 'old'])
  })

  it('不改动传入的数组', () => {
    const list = [style({ id: 'b', name: 'b' }), style({ id: 'a', name: 'a' })]
    sortStyles(list)
    expect(list.map((s) => s.id)).toEqual(['b', 'a'])
  })
})
