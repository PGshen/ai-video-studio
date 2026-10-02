import { describe, expect, it } from 'vitest'
import { formatSnapshotTime } from './snapshotTime'

describe('formatSnapshotTime', () => {
  it('没有时区后缀的服务器时间按 UTC 解析，显示本地的 月-日 时:分', () => {
    const expected = new Date('2026-10-01T14:50:26.279567Z')
    const pad = (n: number) => String(n).padStart(2, '0')
    expect(formatSnapshotTime('2026-10-01T14:50:26.279567')).toBe(
      `${pad(expected.getMonth() + 1)}-${pad(expected.getDate())} ${pad(expected.getHours())}:${pad(expected.getMinutes())}`,
    )
  })

  it('无法解析时原样返回，不丢信息', () => {
    expect(formatSnapshotTime('not-a-time')).toBe('not-a-time')
  })
})
