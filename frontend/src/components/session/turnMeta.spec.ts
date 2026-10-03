import { describe, expect, it } from 'vitest'
import type { TurnOut } from '@/types/api'
import { formatClock, formatTurnMeta } from './turnMeta'

const localClock = (date: Date) =>
  `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`

function turn(overrides: Partial<TurnOut> = {}): TurnOut {
  const created = new Date(2026, 0, 1, 22, 53, 0)
  return {
    id: 't1',
    session_id: 's1',
    user_message: '你好',
    status: 'done',
    start_snapshot_id: null,
    end_snapshot_id: null,
    usage: { input_tokens: 50000, output_tokens: 1000 },
    cost_usd: null,
    error: null,
    never_started: false,
    created_at: created.toISOString(),
    updated_at: new Date(created.getTime() + 6000).toISOString(),
    ...overrides,
  }
}

describe('formatClock', () => {
  it('本地时间 HH:mm，补零', () => {
    expect(formatClock(new Date(2026, 0, 1, 7, 5).toISOString())).toBe('07:05')
    expect(formatClock(new Date(2026, 0, 1, 22, 53).toISOString())).toBe('22:53')
  })

  it('后端返回的时间没有时区后缀时按 UTC 解析（否则东八区会差 8 小时）', () => {
    const utc = new Date(Date.UTC(2026, 9, 1, 17, 0, 48))

    expect(formatClock('2026-10-01T17:00:48.946620')).toBe(localClock(utc))
    expect(formatClock('2026-10-01T17:00:48')).toBe(localClock(utc))
  })

  it('带 Z 或显式偏移的时间按其自身时区解析', () => {
    const utc = new Date(Date.UTC(2026, 9, 1, 17, 0, 48))

    expect(formatClock('2026-10-01T17:00:48Z')).toBe(localClock(utc))
    expect(formatClock('2026-10-02T01:00:48+08:00')).toBe(localClock(utc))
  })

  it('非法时间返回空串', () => {
    expect(formatClock('nope')).toBe('')
  })
})

describe('formatTurnMeta', () => {
  it('给出用量缩写、用时和时间', () => {
    expect(formatTurnMeta(turn())).toEqual({ tokens: '51K', duration: '6 秒', time: '22:53' })
  })

  it('turn 缺失或还没结束返回 null', () => {
    expect(formatTurnMeta(undefined)).toBeNull()
    expect(formatTurnMeta(turn({ status: 'running' }))).toBeNull()
    expect(formatTurnMeta(turn({ status: 'queued' }))).toBeNull()
  })

  it('用量缺失时只省略 tokens', () => {
    const meta = formatTurnMeta(turn({ usage: null }))

    expect(meta?.tokens).toBeUndefined()
    expect(meta?.duration).toBe('6 秒')
    const partial = formatTurnMeta(turn({ usage: { input_tokens: 'x' } }))
    expect(partial?.tokens).toBeUndefined()
  })

  it('有缓存读取数据时给出输出 / 输入 / 缓存的拆分，旧数据没有拆分', () => {
    const withCache = formatTurnMeta(
      turn({ usage: { input_tokens: 229_000, output_tokens: 24_200, cache_read_tokens: 221_000 } }),
    )
    expect(withCache?.tokenBreakdown).toBe('输出 24K · 输入 229K（缓存 221K）')
    // 总量字段保持不变，旧调用方不受影响
    expect(withCache?.tokens).toBe('253K')

    expect(formatTurnMeta(turn())?.tokenBreakdown).toBeUndefined()
  })

  it.each([
    [0, '0'],
    [999, '999'],
    [1234, '1.2K'],
    [9999, '10K'],
    [14123, '14K'],
    [51000, '51K'],
    [999_999, '1000K'],
    [1_234_567, '1.2M'],
  ])('%i token 缩写为 %s', (total, label) => {
    expect(formatTurnMeta(turn({ usage: { input_tokens: total, output_tokens: 0 } }))?.tokens).toBe(
      label,
    )
  })

  it.each([
    [200, '不到 1 秒'],
    [6000, '6 秒'],
    [59_400, '59 秒'],
    [72_000, '1 分 12 秒'],
    [120_000, '2 分'],
  ])('用时 %i 毫秒显示为 %s', (ms, label) => {
    const base = turn()
    const meta = formatTurnMeta(
      turn({ updated_at: new Date(new Date(base.created_at).getTime() + ms).toISOString() }),
    )

    expect(meta?.duration).toBe(label)
  })

  it('时间非法时没有用时，且整体返回 null（没有可显示的时间）', () => {
    expect(formatTurnMeta(turn({ created_at: 'bad' }))).toBeNull()
  })

  it('没有时区后缀的时间戳也能算出用时', () => {
    const meta = formatTurnMeta(
      turn({ created_at: '2026-10-01T17:00:48.000000', updated_at: '2026-10-01T17:00:54.000000' }),
    )

    expect(meta?.duration).toBe('6 秒')
    expect(meta?.time).toBe(localClock(new Date(Date.UTC(2026, 9, 1, 17, 0, 48))))
  })

  it('updated_at 早于 created_at 时不显示用时', () => {
    const base = turn()
    const meta = formatTurnMeta(
      turn({ updated_at: new Date(new Date(base.created_at).getTime() - 5000).toISOString() }),
    )

    expect(meta?.duration).toBeUndefined()
  })
})
