/**
 * 回退建议的处理流程（计划 M5 T13，设计 §5.4）的纯逻辑：卡片上有哪些动作、「去处理」怎么走、
 * 预填文本、跳转地址、阶段角标。组件只负责渲染和调接口。
 *
 * 处理方式：点「去处理」→ 目标阶段已定稿要先确认并重新打开 → 跳到目标阶段并把建议内容预填进输入框
 * → 使用者发送后建议才标为 `applied`（发送失败则仍是 `open`）；「忽略」直接标为 `dismissed`。
 */

import { encodePathSegment } from '@/api/http'
import type { SuggestionStatus } from '@/types/api'

export const STAGE_TITLES: Record<string, string> = {
  topic: '选题',
  narrative: '叙事',
  animation: '动画',
}

export type GoAction =
  | { kind: 'go' }
  | { kind: 'reopen_then_go' }
  | { kind: 'unavailable'; reason: string }

/** 目标阶段的状态 → 「去处理」怎么走。 */
export function goToAction(targetStageStatus: string | undefined): GoAction {
  switch (targetStageStatus) {
    case 'active':
      return { kind: 'go' }
    case 'finalized':
    case 'stale':
      return { kind: 'reopen_then_go' }
    case 'locked':
      return { kind: 'unavailable', reason: '上游阶段还未开放' }
    default:
      return { kind: 'unavailable', reason: '阶段状态还没加载出来' }
  }
}

export interface CardActions {
  go: boolean
  dismiss: boolean
  /** 「去处理」不能点的原因；`null` 表示可点。 */
  goDisabledReason: string | null
}

/** 卡片上的按钮：只有待处理（`open`）的建议才有；目标阶段未开放时「去处理」禁用并说明。 */
export function cardActions(status: SuggestionStatus, targetStageStatus: string | undefined): CardActions {
  if (status !== 'open') return { go: false, dismiss: false, goDisabledReason: null }
  const action = goToAction(targetStageStatus)
  return {
    go: true,
    dismiss: true,
    goDisabledReason: action.kind === 'unavailable' ? action.reason : null,
  }
}

/** 预填进输入框的文本：写明来源阶段和建议内容，使用者可以改。 */
export function prefillText(suggestion: { from_stage: string; content: string }): string {
  const from = STAGE_TITLES[suggestion.from_stage] ?? suggestion.from_stage
  return `下游的${from}阶段提出了一条修改建议，请评估并按需修改：\n${suggestion.content}`
}

export function suggestionRoute(projectId: string, toStage: string, suggestionId: string): string {
  return `/projects/${encodePathSegment(projectId)}/${encodePathSegment(toStage)}?suggestion=${encodeURIComponent(suggestionId)}`
}

/** 阶段导航角标：该阶段还有几条待处理的建议。 */
export function badgeCount(summary: Record<string, number> | undefined, stage: string): number {
  return summary?.[stage] ?? 0
}
