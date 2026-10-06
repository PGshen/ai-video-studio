/**
 * 把定稿按钮和快照栏开关放进自己标签行（`actions` 槽）的阶段画布。其余阶段走通用画布，由工作台页面
 * 在画布上方统一放一行；两处同时出现就会重复（3B 的 L4 在配乐阶段发现过）。
 */
export const STAGES_WITH_OWN_ACTIONS: readonly string[] = [
  'topic',
  'narrative',
  'music',
  'produce',
  'animation',
  'animation_html',
]
