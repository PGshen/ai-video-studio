import { describe, expect, it } from 'vitest'
import { snapshotReasonLabel } from './snapshotReason'

describe('snapshotReasonLabel', () => {
  it.each([
    ['init', '初始化'],
    ['turn', 'Agent 一轮'],
    ['user_edit', '手动编辑'],
    ['rollback', '回滚'],
    ['partial', '中断（部分完成）'],
  ])('%s -> %s', (reason, label) => {
    expect(snapshotReasonLabel(reason)).toBe(label)
  })

  it('未知取值原样返回', () => {
    expect(snapshotReasonLabel('mystery')).toBe('mystery')
  })
})
