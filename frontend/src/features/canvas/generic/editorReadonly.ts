/**
 * 通用文件画布里 CodeEditor 是否只读（任务简报 T14，控制者裁定 2）：
 *
 * - agent 正在这个项目里跑一轮（后端按项目串行，`busy` 由页面根据当前
 *   会话的 turn 状态算出——见 `components/session/turnControls.ts` 的
 *   `isBusyStatus`——传进来，这里不关心状态字符串本身）；
 * - 或者文件在 `upstream/` 下（`FileEntry.readonly`）。
 *
 * 是否落在阶段可写范围之外**不**在这里判断——那需要复刻后端 `is_writable`
 * 的完整规则（§4.3），保存时后端会用真实规则拒绝（403），前端只负责把
 * 错误展示清楚（见 `FileCanvas.vue`）。这里只做"确定能提前挡住"的两种
 * 情况，纯函数，方便单测覆盖每种组合。
 */

export interface ReadonlyInput {
  busy: boolean
  isUpstream: boolean
}

export type ReadonlyReason = 'busy' | 'upstream' | null

export interface ReadonlyDecision {
  readonly: boolean
  reason: ReadonlyReason
}

export function computeReadonly({ busy, isUpstream }: ReadonlyInput): ReadonlyDecision {
  if (busy) return { readonly: true, reason: 'busy' }
  if (isUpstream) return { readonly: true, reason: 'upstream' }
  return { readonly: false, reason: null }
}
