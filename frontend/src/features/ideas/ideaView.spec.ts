import { describe, expect, it } from 'vitest'
import type { IdeaOut } from '@/types/api'
import {
  SCORE_DIMENSIONS,
  allTags,
  emptyDraft,
  draftFromIdea,
  draftToPayload,
  filterIdeas,
  ideaTotal,
  parseTags,
  statusLabel,
} from './ideaView'

function idea(overrides: Partial<IdeaOut> = {}): IdeaOut {
  return {
    id: 'i1',
    title: '排序为什么这么快',
    pitch: '十亿条记录一秒排完',
    counterintuitive: '大家以为排序慢',
    tags: ['算法', '排序'],
    scores: { counterintuitive: 5, visual: 3 },
    status: 'idea',
    project_id: null,
    source_session_id: null,
    created_at: '2026-09-29T00:00:00Z',
    updated_at: '2026-09-29T00:00:00Z',
    ...overrides,
  }
}

describe('SCORE_DIMENSIONS', () => {
  it('和后端的四个评分维度一致，并带中文标签', () => {
    expect(SCORE_DIMENSIONS.map((d) => d.key)).toEqual([
      'counterintuitive',
      'provable',
      'visual',
      'novelty',
    ])
    expect(SCORE_DIMENSIONS.map((d) => d.label)).toEqual(['反直觉', '可论证', '可视化', '新鲜度'])
  })
})

describe('ideaTotal', () => {
  it('把已评的维度相加，并给出评了几项', () => {
    expect(ideaTotal({ counterintuitive: 5, visual: 3 })).toEqual({ sum: 8, count: 2 })
  })
  it('没有评分时为 0/0', () => {
    expect(ideaTotal({})).toEqual({ sum: 0, count: 0 })
  })
})

describe('parseTags', () => {
  it('按逗号、顿号、空白切分，去空、去重，保持顺序', () => {
    expect(parseTags('算法, 排序，算法、 分治  数据结构')).toEqual([
      '算法',
      '排序',
      '分治',
      '数据结构',
    ])
  })
  it('空输入得到空数组', () => {
    expect(parseTags('  ')).toEqual([])
  })
})

describe('filterIdeas / allTags', () => {
  const ideas = [
    idea({ id: 'a', title: '排序', tags: ['算法'] }),
    idea({ id: 'b', title: '黑洞', pitch: '视界', tags: ['物理'] }),
    idea({ id: 'c', title: '哈希表', pitch: null, counterintuitive: null, tags: ['算法', '数据结构'] }),
  ]

  it('按标签筛选', () => {
    expect(filterIdeas(ideas, { query: '', tag: '算法' }).map((i) => i.id)).toEqual(['a', 'c'])
  })
  it('按关键词匹配标题、卖点、反直觉点、标签（不区分大小写）', () => {
    expect(filterIdeas(ideas, { query: '视界', tag: null }).map((i) => i.id)).toEqual(['b'])
    expect(filterIdeas(ideas, { query: '数据', tag: null }).map((i) => i.id)).toEqual(['c'])
    expect(filterIdeas([idea({ title: 'Hash' })], { query: 'hASH', tag: null })).toHaveLength(1)
  })
  it('没有条件时原样返回', () => {
    expect(filterIdeas(ideas, { query: ' ', tag: null })).toHaveLength(3)
  })
  it('allTags 去重并按出现次数从多到少排序', () => {
    expect(allTags(ideas)).toEqual(['算法', '物理', '数据结构'])
  })
})

describe('statusLabel', () => {
  it('给出中文状态', () => {
    expect(statusLabel('idea')).toBe('未使用')
    expect(statusLabel('picked')).toBe('已创建项目')
    expect(statusLabel('archived')).toBe('已归档')
    expect(statusLabel('weird')).toBe('weird')
  })
})

describe('draft 转换', () => {
  it('emptyDraft 是空表单', () => {
    expect(emptyDraft()).toEqual({
      title: '',
      pitch: '',
      counterintuitive: '',
      tags: '',
      scores: {},
    })
  })
  it('draftFromIdea 把卡片转成表单，null 变空串，标签用顿号连接', () => {
    const draft = draftFromIdea(idea({ pitch: null }))
    expect(draft.pitch).toBe('')
    expect(draft.tags).toBe('算法、排序')
    expect(draft.scores).toEqual({ counterintuitive: 5, visual: 3 })
  })
  it('draftToPayload 去首尾空白，空文本变 null，标签解析为数组，评分原样带上', () => {
    expect(
      draftToPayload({
        title: '  T  ',
        pitch: ' ',
        counterintuitive: 'c',
        tags: 'a, b',
        scores: { novelty: 2 },
      }),
    ).toEqual({ title: 'T', pitch: null, counterintuitive: 'c', tags: ['a', 'b'], scores: { novelty: 2 } })
  })
})
