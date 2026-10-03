/** 列表分页的纯逻辑（选题池和项目列表共用；features/* 之间不能互相 import，所以放在这里）。 */

export const PAGE_SIZE = 12

/** 总页数，没有数据时也是 1 页。 */
export function pageCount(total: number, size: number): number {
  return Math.max(1, Math.ceil(total / size))
}

/** 取第 `page` 页（从 1 开始）；越界的页码收进有效范围。 */
export function paginate<T>(items: readonly T[], page: number, size: number): T[] {
  const clamped = Math.min(Math.max(1, page), pageCount(items.length, size))
  return items.slice((clamped - 1) * size, clamped * size)
}
