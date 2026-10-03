import { describe, expect, it } from 'vitest'
import { pageCount, paginate } from './pagination'

describe('分页', () => {
  const items = Array.from({ length: 25 }, (_, i) => i + 1)

  it('pageCount 至少 1 页', () => {
    expect(pageCount(0, 12)).toBe(1)
    expect(pageCount(12, 12)).toBe(1)
    expect(pageCount(13, 12)).toBe(2)
    expect(pageCount(25, 12)).toBe(3)
  })
  it('paginate 取出当前页，页码从 1 开始', () => {
    expect(paginate(items, 1, 12)).toEqual(items.slice(0, 12))
    expect(paginate(items, 3, 12)).toEqual([25])
  })
  it('paginate 把越界页码收进有效范围', () => {
    expect(paginate(items, 0, 12)).toEqual(items.slice(0, 12))
    expect(paginate(items, 9, 12)).toEqual([25])
    expect(paginate([], 5, 12)).toEqual([])
  })
})
