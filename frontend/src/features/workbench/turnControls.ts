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

/**
 * 项目是否"忙"（有一轮在跑）：T14 通用文件画布用它决定 CodeEditor 是否
 * 只读——后端按项目串行（同一时间只有一个 turn 在写工作区），所以当前
 * 会话的 turn 处于 `queued`/`running` 就足以代表整个项目忙，不需要单独
 * 的项目级接口。
 */
export function isBusyStatus(status: string | null): boolean {
  return status !== null && BUSY_STATUSES.has(status)
}

/**
 * 通用文件画布/快照时间线是否只读，综合两个信号（T14 审查修复：原来只看
 * 当前选中会话的 turn 状态，但后端按**项目**串行——用户可能开着另一个
 * 会话、或者另一个浏览器标签页在跑一轮，`GET /projects/{id}` 的 `busy`
 * 字段才是权威来源；见 `docs/plans/active/m1-skeleton.md` 决策记录）：
 * - `projectBusy`：`ProjectDetailOut.busy`，来自轮询（`useProjectQuery`
 *   的 `refetchInterval`），可能滞后几秒；
 * - `sessionStatus`：当前选中会话的 turn 状态，来自 SSE（`turn_status`
 *   事件），近乎实时，但只覆盖"当前正在看的这个会话"。
 * 两者取或：只要有一个说"忙"就是忙，用滞后换取"自己这个会话一开始/
 * 结束就立刻生效"的即时性，同时不漏掉"别处在跑"的情况。
 */
export function combineBusy(projectBusy: boolean, sessionStatus: string | null): boolean {
  return projectBusy || isBusyStatus(sessionStatus)
}
