/**
 * 当前打开的镜头代码文件从工作区消失时的处理决策（任务 T12，决策记录
 * D36）：和 `features/canvas/generic/missingFile.ts`（追加修复 G1）逻辑
 * 完全一样——同样的道理，`animation/scenes/<id>.py` 也可能因为回滚/被
 * agent 删除而消失，用户如果正编辑着它，不能让编辑器悄悄用旧内容覆盖式
 * 保存把文件重新创建出来。跨阶段画布不能互相 import（见
 * `conflictState.ts` 顶部注释），复制一份。
 *
 * 注意：这个函数只处理"之前已经加载过真实内容、后来消失了"的情况；
 * "这个镜头从来没有写过代码"（`SceneStatus.exists === false` 但用户是
 * 第一次选中它）不算"消失"，那种情况由 `AnimationCanvas.vue` 直接初始化
 * 一个空的可编辑缓冲区，不会调用到这里。
 *
 * - 缓冲区干净：关闭编辑器，回到"从左侧选择一个镜头"的占位态。
 * - 缓冲区脏：不自动关闭、不自动重建文件，保留内容只读展示，并提示
 *   "该文件已不存在（可能被回滚或删除）"。
 */

export interface MissingFileInput {
  fileMissing: boolean
  dirty: boolean
}

export type MissingFileAction = 'none' | 'close' | 'keep-readonly'

export function computeMissingFileAction({ fileMissing, dirty }: MissingFileInput): MissingFileAction {
  if (!fileMissing) return 'none'
  return dirty ? 'keep-readonly' : 'close'
}
