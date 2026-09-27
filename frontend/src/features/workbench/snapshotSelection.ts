/**
 * 快照时间线的多选与 diff 请求参数（任务简报 T14，控制者裁定 5）：最多选
 * 两个快照，选中第三个时挤掉最早选中的那个；选够两个后算出
 * `diffSnapshots` 的 `{from, to}`——`from` 是较早的快照，`to` 是较晚的，
 * 与快照在列表里的相对位置有关（不看 `created_at` 字符串比较，直接用列表
 * 顺序，调用方负责按什么顺序传列表——`SnapshotTimeline.vue` 传的是
 * "最新在前"的展示顺序）。
 */

export function toggleSnapshotSelection(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((existing) => existing !== id)
  if (selected.length < 2) return [...selected, id]
  return [selected[1]!, id] // 挤掉最早选中的那个（selected[0]）。
}

export interface SnapshotLike {
  id: string
}

/**
 * `snapshots` 必须是"最新在前"的顺序（`SnapshotTimeline.vue` 展示用的
 * 顺序）；返回 `null` 表示还没选够两个，或者选中的 id 不在列表里。
 */
export function computeDiffParams(
  snapshots: SnapshotLike[],
  selected: string[],
): { from: string; to: string } | null {
  if (selected.length !== 2) return null
  const [a, b] = selected as [string, string]
  const indexOf = new Map(snapshots.map((snapshot, index) => [snapshot.id, index]))
  const indexA = indexOf.get(a)
  const indexB = indexOf.get(b)
  if (indexA === undefined || indexB === undefined) return null
  // 列表最新在前：下标更小 = 更新。from 取较早（下标更大）的一个。
  return indexA < indexB ? { from: b, to: a } : { from: a, to: b }
}

/**
 * [回滚到此] 是否可点（T14 审查修复：原来一直可点，即使 agent 正在运行
 * 也能点开二次确认弹窗，后端才会在真正提交时返回 409）。`[对比]`
 * （`toggle`）不受这个限制——只是选中快照、本地算 diff，不改工作区，
 * `busy` 时也可以看。
 */
export function canRollback(busy: boolean, isPending: boolean): boolean {
  return !busy && !isPending
}
