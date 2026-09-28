/**
 * 当前打开的文件从文件树消失时的处理决策（追加修复 G1，2026-09-28）：
 * 控制者浏览器走查发现——打开 `topic/fake-note.md` → 回滚到不含该文件的
 * 快照 → 文件树已更新（文件消失），但 `FileCanvas` 的编辑器仍显示已删除
 * 文件的旧内容，容易让用户误以为文件还在、继续编辑后保存会意外把它
 * 在原路径重新创建出来。
 *
 * 选择最小、不丢用户修改的方案（未采用[另存为原路径重新创建]/[丢弃]
 * 的横幅交互——"重新创建"算不算新一轮改动、要不要立刻写工作区，这些
 * 语义还没想清楚，留给以后真的需要时再做）：
 *
 * - 缓冲区干净（没有未保存修改）：关闭编辑器，`FileCanvas.vue` 把
 *   `selectedPath` 清空，回到"从左侧选择一个文件"的占位态。
 * - 缓冲区脏（有未保存修改）：不自动关闭、不自动重建文件，保留内容
 *   只读展示，并提示"该文件已不存在（可能被回滚或删除）"。
 *
 * 纯函数，`FileCanvas.vue` 是唯一调用方。
 */

export interface MissingFileInput {
  /** 当前选中的文件是否已经不在文件树里（或内容查询返回 404）。 */
  fileMissing: boolean
  /** 缓冲区是否有未保存的修改。 */
  dirty: boolean
}

export type MissingFileAction = 'none' | 'close' | 'keep-readonly'

export function computeMissingFileAction({ fileMissing, dirty }: MissingFileInput): MissingFileAction {
  if (!fileMissing) return 'none'
  return dirty ? 'keep-readonly' : 'close'
}
