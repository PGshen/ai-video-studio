/**
 * HTML 画布的标签页与默认页（free-mode 设计 §6.2）：纯函数，按阶段和调用方提供了哪些插槽决定。
 *
 * - `animation_html`：镜头 / 实时预览 / 成片 / 文件（插槽）。
 * - `produce`：多一个由插槽提供的「配乐」。
 * - 所有阶段：给了「文件」插槽就在最后加「文件」（工作台每个阶段都给，方便看工作区里有哪些文件）。
 * - `free_explainer`：叙事（插槽）/ 镜头 / 实时预览 / 配乐（插槽）/ 成片 / 文件（插槽），默认实时预览。
 * - `free_produce`：同上但没有叙事。
 */

export type CanvasStage = 'animation_html' | 'produce' | 'free_explainer' | 'free_produce'
export type CanvasTab = 'narrative' | 'scenes' | 'preview' | 'music' | 'final' | 'files'

export interface CanvasSlots {
  narrative: boolean
  music: boolean
  files: boolean
}

export function isFreeStage(stage: CanvasStage): boolean {
  return stage === 'free_explainer' || stage === 'free_produce'
}

export function canvasTabs(
  stage: CanvasStage,
  slots: CanvasSlots,
): { tabs: CanvasTab[]; initial: CanvasTab } {
  const free = isFreeStage(stage)
  const tabs: CanvasTab[] = []
  if (stage === 'free_explainer' && slots.narrative) tabs.push('narrative')
  tabs.push('scenes', 'preview')
  if (stage !== 'animation_html' && slots.music) tabs.push('music')
  tabs.push('final')
  if (slots.files) tabs.push('files')
  return { tabs, initial: free ? 'preview' : 'scenes' }
}
