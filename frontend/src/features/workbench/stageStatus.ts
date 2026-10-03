/**
 * 阶段导航的状态 → 样式/可点性映射（任务简报 T13，控制者裁定 5）。纯函数，
 * 不依赖组件实例，方便单测；`StageNav.vue` 只负责把结果绑到模板上。
 *
 * 后端四种阶段状态（`backend/src/studio/db/models.py`、`agent/stage_flow.py`）：
 * `locked`（还没轮到，灰、禁用）、`active`（当前可对话）、`finalized`（已定稿，
 * 打勾）、`stale`（已定稿但上游又变了，警告）。
 */

export interface StageStatusStyle {
  disabled: boolean
  /** 附加在阶段名后面的角标：`✓`（finalized）/`⚠`（stale）/空字符串。 */
  suffix: string
  className: string
}

const STYLES: Record<string, StageStatusStyle> = {
  locked: { disabled: true, suffix: '', className: 'text-muted-foreground opacity-50' },
  active: { disabled: false, suffix: '', className: 'text-foreground font-medium' },
  finalized: { disabled: false, suffix: '✓', className: 'text-foreground' },
  stale: { disabled: false, suffix: '⚠', className: 'text-amber-600' },
}

const DEFAULT_STYLE: StageStatusStyle = { disabled: false, suffix: '', className: '' }

export function stageStatusStyle(status: string): StageStatusStyle {
  return STYLES[status] ?? DEFAULT_STYLE
}

/** 阶段 id → 中文名（导航条和项目「信息」共用）。 */
export const STAGE_TITLES: Record<string, string> = {
  topic: '选题',
  narrative: '叙事',
  animation: '动画',
}
