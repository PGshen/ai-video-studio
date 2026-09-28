import { describe, expect, it } from 'vitest'
import { canRollback, computeDiffParams, toggleSnapshotSelection } from './snapshotSelection'

describe('toggleSnapshotSelection', () => {
  it('从空选中一个', () => {
    expect(toggleSnapshotSelection([], 'a')).toEqual(['a'])
  })

  it('已选一个时再选一个，凑够两个', () => {
    expect(toggleSnapshotSelection(['a'], 'b')).toEqual(['a', 'b'])
  })

  it('选够两个后再选第三个：挤掉最早选中的', () => {
    expect(toggleSnapshotSelection(['a', 'b'], 'c')).toEqual(['b', 'c'])
  })

  it('再次点击已选中的项：取消选中', () => {
    expect(toggleSnapshotSelection(['a', 'b'], 'a')).toEqual(['b'])
  })
})

describe('computeDiffParams', () => {
  // 最新在前的展示顺序。
  const snapshots = [{ id: 's3' }, { id: 's2' }, { id: 's1' }]

  it('没选够两个时返回 null', () => {
    expect(computeDiffParams(snapshots, [])).toBeNull()
    expect(computeDiffParams(snapshots, ['s1'])).toBeNull()
  })

  it('选中的 id 不在列表里时返回 null', () => {
    expect(computeDiffParams(snapshots, ['s1', 'unknown'])).toBeNull()
  })

  it('按列表顺序算出 from（较早）/to（较晚），与选择顺序无关', () => {
    expect(computeDiffParams(snapshots, ['s1', 's3'])).toEqual({ from: 's1', to: 's3' })
    expect(computeDiffParams(snapshots, ['s3', 's1'])).toEqual({ from: 's1', to: 's3' })
  })
})

describe('canRollback', () => {
  it('既不忙、也没有请求在飞：可以回滚', () => {
    expect(canRollback(false, false)).toBe(true)
  })

  it('agent 正在运行：不能回滚', () => {
    expect(canRollback(true, false)).toBe(false)
  })

  it('回滚请求本身还在飞：不能再点一次', () => {
    expect(canRollback(false, true)).toBe(false)
  })

  it('两者都成立：不能回滚', () => {
    expect(canRollback(true, true)).toBe(false)
  })
})
