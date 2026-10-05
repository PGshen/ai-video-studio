/**
 * 配乐画布的展示换算（纯函数）：把 `analysis.json` 里的 `metrics`（后端 `metrics_of` 的输出）整理成
 * 可展示的行。字段缺失或类型不对一律跳过，不让坏数据把画布弄崩。
 */

export function formatClock(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  const minutes = Math.floor(whole / 60)
  return `${minutes}:${(whole - minutes * 60).toFixed(1).padStart(4, '0')}`
}

type Metrics = Record<string, unknown> | null | undefined

export interface MetricRow {
  label: string
  value: string
}

function numberOf(metrics: Metrics, key: string): number | null {
  const value = metrics?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function metricRows(metrics: Metrics): MetricRow[] {
  const rows: MetricRow[] = []
  const peak = numberOf(metrics, 'peak_dbfs')
  if (peak !== null) rows.push({ label: '峰值', value: `${peak.toFixed(1)} dBFS` })
  const rms = numberOf(metrics, 'rms_dbfs')
  if (rms !== null) rows.push({ label: '整体响度（RMS）', value: `${rms.toFixed(1)} dBFS` })
  const clipped = numberOf(metrics, 'clipped_samples')
  if (clipped !== null) rows.push({ label: '削波样本', value: String(clipped) })
  const alignment = numberOf(metrics, 'grid_alignment')
  if (alignment !== null) {
    rows.push({ label: '起音对齐网格', value: `${Math.round(alignment * 100)}%` })
  }
  const onsets = numberOf(metrics, 'onsets')
  if (onsets !== null) rows.push({ label: '检测到的起音', value: String(onsets) })
  return rows
}

export interface MatchRow {
  name: string
  matched: number
  detectable: number
}

/** 声明的起音事件与实测起音的匹配，按事件名合计（同名事件可能分多条）。 */
export function matchRows(metrics: Metrics): MatchRow[] {
  const raw = metrics?.event_matches
  if (!Array.isArray(raw)) return []
  const byName = new Map<string, MatchRow>()
  for (const item of raw) {
    if (item === null || typeof item !== 'object') continue
    const { name, detectable, matched } = item as Record<string, unknown>
    if (typeof name !== 'string' || typeof detectable !== 'number' || typeof matched !== 'number') {
      continue
    }
    const row = byName.get(name) ?? { name, matched: 0, detectable: 0 }
    row.matched += matched
    row.detectable += detectable
    byName.set(name, row)
  }
  return [...byName.values()]
}

export function metricWarnings(metrics: Metrics): string[] {
  const raw = metrics?.warnings
  return Array.isArray(raw) ? raw.filter((w): w is string => typeof w === 'string') : []
}
