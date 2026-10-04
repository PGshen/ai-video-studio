/** 风格库列表的纯逻辑：筛选、分类、排序（列表页和测试共用）。 */
import type { StyleSummaryOut } from '@/types/api'

export interface StyleFilter {
  keyword: string
  /** `null` 不按分类筛。 */
  category: string | null
  onlyDefault: boolean
}

/** 关键词匹配名称、简介和分类（忽略大小写和首尾空白）；分类精确匹配；条件叠加。 */
export function filterStyles(
  styles: readonly StyleSummaryOut[],
  filter: StyleFilter,
): StyleSummaryOut[] {
  const keyword = filter.keyword.trim().toLowerCase()
  return styles.filter((style) => {
    if (filter.onlyDefault && !style.is_default) return false
    if (filter.category !== null && style.category !== filter.category) return false
    if (keyword === '') return true
    return [style.name, style.description ?? '', style.category].some((text) =>
      text.toLowerCase().includes(keyword),
    )
  })
}

/** 出现过的分类，去重并排序。 */
export function allCategories(styles: readonly StyleSummaryOut[]): string[] {
  return [...new Set(styles.map((style) => style.category))].sort((a, b) => a.localeCompare(b))
}

/** 默认风格在前，其余按最近修改倒序，同时间按名称。不改动传入的数组。 */
export function sortStyles(styles: readonly StyleSummaryOut[]): StyleSummaryOut[] {
  return [...styles].sort((a, b) => {
    if (a.is_default !== b.is_default) return a.is_default ? -1 : 1
    const byTime = Date.parse(b.modified_at) - Date.parse(a.modified_at)
    return byTime !== 0 ? byTime : a.name.localeCompare(b.name)
  })
}
