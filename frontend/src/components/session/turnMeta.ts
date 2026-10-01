/**
 * 回复操作栏和用户气泡用的 turn 元信息：用量缩写、用时、时钟。数据来自 `TurnOut`
 * （`usage`、`created_at`、`updated_at`），不需要后端新字段。
 */
import type { TurnOut } from '@/types/api'

export interface TurnMeta {
  /** 例如 `51K`；`usage` 缺失或无数字时没有。 */
  tokens?: string
  /** 例如 `6 秒`、`1 分 12 秒`；时间不合法或倒挂时没有。 */
  duration?: string
  /** 创建时间的本地 `HH:mm`。 */
  time: string
}

const pad = (n: number) => String(n).padStart(2, '0')

export function formatClock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function trimZero(text: string): string {
  return text.replace(/\.0$/, '')
}

function formatTokens(total: number): string {
  if (total < 1000) return String(total)
  if (total < 10_000) return `${trimZero((total / 1000).toFixed(1))}K`
  if (total < 1_000_000) return `${Math.round(total / 1000)}K`
  return `${trimZero((total / 1_000_000).toFixed(1))}M`
}

function tokensOf(usage: TurnOut['usage']): string | undefined {
  if (!usage) return undefined
  const parts = [usage.input_tokens, usage.output_tokens].filter(
    (value): value is number => typeof value === 'number' && Number.isFinite(value),
  )
  return parts.length === 0 ? undefined : formatTokens(parts.reduce((a, b) => a + b, 0))
}

function formatDuration(ms: number): string | undefined {
  if (!Number.isFinite(ms) || ms < 0) return undefined
  if (ms < 1000) return '不到 1 秒'
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest === 0 ? `${minutes} 分` : `${minutes} 分 ${rest} 秒`
}

/** turn 缺失、还在排队/运行、或时间不合法时返回 `null`（整行不显示）。 */
export function formatTurnMeta(turn: TurnOut | undefined): TurnMeta | null {
  if (!turn || turn.status === 'queued' || turn.status === 'running') return null
  const time = formatClock(turn.created_at)
  if (time === '') return null
  const meta: TurnMeta = { time }
  const tokens = tokensOf(turn.usage)
  if (tokens !== undefined) meta.tokens = tokens
  const duration = formatDuration(
    new Date(turn.updated_at).getTime() - new Date(turn.created_at).getTime(),
  )
  if (duration !== undefined) meta.duration = duration
  return meta
}
