/**
 * 回复操作栏和用户气泡用的 turn 元信息：用量缩写、用时、时钟，以及「命令未隔离」标记。数据来自
 * `TurnOut`（`usage`、`created_at`、`updated_at`；`usage.exec_mode` 见 ADR 0024）。
 */
import type { TurnOut } from '@/types/api'

export interface TurnMeta {
  /** 例如 `51K`；`usage` 缺失或无数字时没有。 */
  tokens?: string
  /**
   * 例如 `输出 24K · 输入 229K（缓存 221K）`。输入大头通常是 agent 每次调工具重读上下文的缓存命中，
   * 只给总数会误导；`usage` 没有 `cache_read_tokens`（旧数据）时没有。
   */
  tokenBreakdown?: string
  /** 例如 `6 秒`、`1 分 12 秒`；时间不合法或倒挂时没有。 */
  duration?: string
  /** 创建时间的本地 `HH:mm`。 */
  time: string
  /** 这一轮的命令没有经过沙箱（`usage.exec_mode === 'unsandboxed'`，ADR 0024）。 */
  unsandboxed?: boolean
}

const pad = (n: number) => String(n).padStart(2, '0')
const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i

/**
 * 后端（SQLite）返回的时间是**没有时区后缀的 UTC**（如 `2026-10-01T17:00:48.946620`），
 * `new Date()` 会把它当本地时间，东八区就差 8 小时。没有时区信息时按 UTC 解析。
 */
export function parseServerTime(iso: string): Date {
  return new Date(HAS_ZONE.test(iso) ? iso : `${iso}Z`)
}

export function formatClock(iso: string): string {
  const date = parseServerTime(iso)
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

function breakdownOf(usage: TurnOut['usage']): string | undefined {
  if (!usage) return undefined
  const { input_tokens: input, output_tokens: output, cache_read_tokens: cached } = usage
  if (![input, output, cached].every((v) => typeof v === 'number' && Number.isFinite(v))) {
    return undefined
  }
  return `输出 ${formatTokens(output as number)} · 输入 ${formatTokens(input as number)}（缓存 ${formatTokens(cached as number)}）`
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
  const tokenBreakdown = breakdownOf(turn.usage)
  if (tokenBreakdown !== undefined) meta.tokenBreakdown = tokenBreakdown
  const duration = formatDuration(
    parseServerTime(turn.updated_at).getTime() - parseServerTime(turn.created_at).getTime(),
  )
  if (duration !== undefined) meta.duration = duration
  if (turn.usage?.exec_mode === 'unsandboxed') meta.unsandboxed = true
  return meta
}
