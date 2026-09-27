/**
 * 快照 `reason` 字段（后端 `studio.workspace.snapshot`）到中文标签的映射
 * （任务简报 T14，控制者裁定 5）。未知取值原样返回，不隐藏信息。
 */

const REASON_LABELS: Record<string, string> = {
  init: '初始化',
  turn: 'Agent 一轮',
  user_edit: '手动编辑',
  rollback: '回滚',
  partial: '中断（部分完成）',
}

export function snapshotReasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason
}

/**
 * 会话时间线里 `snapshot` 事件的文案（M1 最终审查 M4）：`created=false` 表示
 * 轮末工作区与最近一份快照相同、后端返回的是已有快照，不能说"已创建"。
 */
export function snapshotEventLabel(reason: string, created: boolean): string {
  if (!created) return '本轮没有改动文件，未创建新快照'
  return `已创建快照（${snapshotReasonLabel(reason)}）`
}
