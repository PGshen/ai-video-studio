/**
 * 镜头检查结果（`validate_scenes`/`render_preview`）的展示用摘要：`SceneList.vue`
 * 用 `checkTone` 决定状态图标，用 `checkLabel` 生成悬停说明。纯函数，不依赖组件。
 */
import type { SceneCheckOut } from '@/types/api'

export type CheckTone = 'none' | 'passed' | 'stale' | 'failed'

export function checkTone(check: SceneCheckOut | null): CheckTone {
  if (check === null || check.status === 'not_checked') return 'none'
  if (check.status === 'failed') return 'failed'
  return check.stale ? 'stale' : 'passed'
}

export function checkLabel(prefix: string, check: SceneCheckOut | null): string {
  if (check === null || check.status === 'not_checked') return `${prefix}：未检查`
  const outcome = check.status === 'passed' ? '通过' : '失败'
  return `${prefix}：${outcome}${check.stale ? '（已过期）' : ''}`
}
