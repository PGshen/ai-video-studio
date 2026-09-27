/**
 * 会话面板输入区/按钮的可用性，只看当前 turn 状态（任务简报 T13，控制者
 * 裁定 3）。纯函数，`SessionPanel.vue` 用它决定输入框是否禁用、
 * [停止]/[继续] 是否显示；单测覆盖真实会出现的每一种 `turn_status`。
 *
 * 状态取值见 `backend/src/studio/agent/events.py`（`TurnStatus`）和
 * `db/repo/turns.py`：`queued`/`running`（进行中）、`done`/`failed`/
 * `cancelled`（正常结束，不需要特殊按钮）、`interrupted`/`budget_exceeded`
 * （可以用 [继续] 恢复，但当前输入框仍然可用，用户也可以直接发新消息）。
 */

export interface TurnControls {
  inputDisabled: boolean
  showStop: boolean
  showContinue: boolean
}

const BUSY_STATUSES = new Set(['queued', 'running'])
const RESUMABLE_STATUSES = new Set(['interrupted', 'budget_exceeded'])

const IDLE_CONTROLS: TurnControls = { inputDisabled: false, showStop: false, showContinue: false }

export function computeTurnControls(status: string | null): TurnControls {
  if (status === null) return IDLE_CONTROLS
  if (BUSY_STATUSES.has(status)) {
    return { inputDisabled: true, showStop: true, showContinue: false }
  }
  if (RESUMABLE_STATUSES.has(status)) {
    return { inputDisabled: false, showStop: false, showContinue: true }
  }
  return IDLE_CONTROLS
}
