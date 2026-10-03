/** 选题评分维度和总分（选题池、项目列表和项目「信息」共用；features/* 之间不能互相 import，所以放在这里）。 */

import type { IdeaScoreKey } from '@/types/api'

export const SCORE_DIMENSIONS: ReadonlyArray<{ key: IdeaScoreKey; label: string }> = [
  { key: 'counterintuitive', label: '反直觉' },
  { key: 'provable', label: '可论证' },
  { key: 'visual', label: '可视化' },
  { key: 'novelty', label: '新鲜度' },
]

export function ideaTotal(scores: Partial<Record<IdeaScoreKey, number>>): {
  sum: number
  count: number
} {
  const values = Object.values(scores).filter((v): v is number => typeof v === 'number')
  return { sum: values.reduce((a, b) => a + b, 0), count: values.length }
}
