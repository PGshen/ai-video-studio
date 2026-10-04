/**
 * 时间线里 `notice` 事件的文案（计划 M5 T12）。已知类型用中文标签，带 `message` 时用冒号接在后面；
 * `model_switched`（换模型后第一轮的提示，ADR 0012）和 `draft_pruned`（风格草稿里不属于风格的文件被清除）
 * 的 `message` 本身就是完整的一句话，直接用它。
 */

const NOTICE_LABELS: Record<string, string> = {
  guard_restored: '越界写入已被还原',
  cost_unpriced: '本轮成本未计价（模型配置缺单价）',
  cost_carryover: '本轮成本含上一轮被中断时的残余花费，未参与成本预算判断',
}

export function noticeText(kind: string, message?: string): string {
  if (kind === 'model_switched') return message ?? '模型已切换'
  if (kind === 'draft_pruned') return message ?? '草稿里不属于风格的文件已被清除'
  const label = NOTICE_LABELS[kind] ?? kind
  return message ? `${label}：${message}` : label
}
