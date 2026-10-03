/** 选题评分维度（选题池和项目「信息」共用；features/* 之间不能互相 import，所以放在这里）。 */

import type { IdeaScoreKey } from '@/types/api'

export const SCORE_DIMENSIONS: ReadonlyArray<{ key: IdeaScoreKey; label: string }> = [
  { key: 'counterintuitive', label: '反直觉' },
  { key: 'provable', label: '可论证' },
  { key: 'visual', label: '可视化' },
  { key: 'novelty', label: '新鲜度' },
]
