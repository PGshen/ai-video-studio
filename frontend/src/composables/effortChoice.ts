/**
 * 项目「思考强度」（项目设置 `effort`）的共用逻辑：创建项目的两个对话框和项目设置对话框都用它，
 * 控件是 `components/EffortSelect.vue`。取值和后端 `studio.agent.runtime.EFFORT_LEVELS` 一致；
 * 项目没有设置（旧项目）时后端用 `DEFAULT_EFFORT`，这里的 `DEFAULT_EFFORT` 要与之保持一致。
 */

export type Effort = 'low' | 'medium' | 'high'

export const DEFAULT_EFFORT: Effort = 'medium'

export interface EffortOption {
  value: Effort
  label: string
  hint: string
}

export const EFFORT_OPTIONS: EffortOption[] = [
  { value: 'low', label: '快速', hint: '少思考，最快最省，适合先跑通流程' },
  { value: 'medium', label: '均衡', hint: '默认，思考和速度折中' },
  { value: 'high', label: '深入', hint: '多思考，更慢更贵，适合复杂选题' },
]

/** 项目设置里存的值转成选择器的值；缺失或不合法时回落到默认。 */
export function effortFromSettings(settings: Record<string, unknown> | undefined): Effort {
  const value = settings?.effort
  return EFFORT_OPTIONS.some((option) => option.value === value) ? (value as Effort) : DEFAULT_EFFORT
}
