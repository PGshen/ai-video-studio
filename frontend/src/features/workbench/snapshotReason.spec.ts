import { describe, expect, it } from 'vitest'
import { snapshotEventLabel, snapshotReasonLabel } from './snapshotReason'

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

describe('snapshotEventLabel（M4）', () => {
  it('新建了快照时显示"已创建快照"和原因', () => {
    expect(snapshotEventLabel('turn', true)).toBe('已创建快照（Agent 一轮）')
  })

  it('内容没变、沿用已有快照时不说"已创建"', () => {
    expect(snapshotEventLabel('turn', false)).toBe('本轮没有改动文件，未创建新快照')
  })
})
