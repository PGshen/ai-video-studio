/**
 * 选题池的纯逻辑（计划 M4 T9）：评分维度、总分、筛选、标签解析、表单草稿转换。
 * 组件只做展示和事件，判断都在这里，方便单测。
 */

import type { IdeaCreate, IdeaOut, IdeaScoreKey } from '@/types/api'

export { SCORE_DIMENSIONS, ideaTotal } from '@/composables/ideaScores'

export const MAX_TAGS = 8

/** 卡片上的状态徽标文字：归档、已创建了几个项目，或还没用过。 */
export function statusLabel(status: string, projectCount = 0): string {
  if (status === 'archived') return '已归档'
  if (status !== 'idea') return status
  return projectCount > 0 ? `已创建 ${projectCount} 个项目` : '未使用'
}

/** 按逗号、顿号、空白切分标签，去空、去重，保持出现顺序。 */
export function parseTags(input: string): string[] {
  const tags: string[] = []
  for (const part of input.split(/[,，、\s]+/)) {
    const tag = part.trim()
    if (tag && !tags.includes(tag)) tags.push(tag)
  }
  return tags
}

export interface IdeaFilter {
  query: string
  tag: string | null
}

export function filterIdeas(ideas: readonly IdeaOut[], filter: IdeaFilter): IdeaOut[] {
  const needle = filter.query.trim().toLowerCase()
  return ideas.filter((idea) => {
    if (filter.tag !== null && !idea.tags.includes(filter.tag)) return false
    if (!needle) return true
    const haystacks = [idea.title, idea.pitch ?? '', idea.counterintuitive ?? '', ...idea.tags]
    return haystacks.some((text) => text.toLowerCase().includes(needle))
  })
}

/** 出现过的标签，按出现次数从多到少（次数相同保持首次出现顺序）。 */
export function allTags(ideas: readonly IdeaOut[]): string[] {
  const counts = new Map<string, number>()
  for (const idea of ideas) {
    for (const tag of idea.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([tag]) => tag)
}

/** 编辑/新建对话框里的表单状态：文本字段都是字符串，标签是一个输入框。 */
export interface IdeaDraft {
  title: string
  pitch: string
  counterintuitive: string
  tags: string
  scores: Partial<Record<IdeaScoreKey, number>>
}

export function emptyDraft(): IdeaDraft {
  return { title: '', pitch: '', counterintuitive: '', tags: '', scores: {} }
}

export function draftFromIdea(idea: IdeaOut): IdeaDraft {
  return {
    title: idea.title,
    pitch: idea.pitch ?? '',
    counterintuitive: idea.counterintuitive ?? '',
    tags: idea.tags.join('、'),
    scores: { ...idea.scores },
  }
}

/** 表单 → 请求体：文本去首尾空白，空文本变 `null`（后端据此清空），标签解析成数组。 */
export function draftToPayload(draft: IdeaDraft): Required<IdeaCreate> {
  const text = (value: string): string | null => value.trim() || null
  return {
    title: draft.title.trim(),
    pitch: text(draft.pitch),
    counterintuitive: text(draft.counterintuitive),
    tags: parseTags(draft.tags),
    scores: { ...draft.scores },
  }
}
