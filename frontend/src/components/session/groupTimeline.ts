/**
 * 把扁平时间线归成「活动组」（设计 §2）：同一 turn 里连续的 thinking / tool_call 条目一组，
 * 遇到文本、用户消息、notice、error、snapshot、suggestion 或换 turn 就断开。纯函数，组件
 * 只负责渲染它的输出。
 */
import type { ThinkingItem, TimelineItem, ToolCallItem } from '@/composables/useSessionStream'

export type ActivityEntry = ThinkingItem | ToolCallItem

export interface ActivityGroupBlock {
  kind: 'activity'
  turnId: string
  /** `${turnId}:${首条在 items 里的下标}`：折叠状态的稳定键（items 只追加）。 */
  key: string
  entries: ActivityEntry[]
  /** 末尾的、属于运行中 turn 的组：界面据此默认展开并显示进行中的文案。 */
  running: boolean
}

export type PlainItem = Exclude<TimelineItem, ActivityEntry>
export type TimelineBlock = PlainItem | ActivityGroupBlock

function isActivity(item: TimelineItem): item is ActivityEntry {
  return item.kind === 'thinking' || item.kind === 'tool_call'
}

function isBlankThinking(item: TimelineItem): boolean {
  return item.kind === 'thinking' && item.text.trim() === ''
}

export function groupTimeline(
  items: readonly TimelineItem[],
  runningTurnId: string | null,
): TimelineBlock[] {
  const blocks: TimelineBlock[] = []
  let current: ActivityGroupBlock | null = null

  items.forEach((item, index) => {
    if (isBlankThinking(item)) return // 空白思考既不显示，也不打断前后的分组。
    if (!isActivity(item)) {
      current = null
      blocks.push(item)
      return
    }
    if (current === null || current.turnId !== item.turnId) {
      current = {
        kind: 'activity',
        turnId: item.turnId,
        key: `${item.turnId}:${index}`,
        entries: [],
        running: false,
      }
      blocks.push(current)
    }
    current.entries.push(item)
  })

  const last = blocks.at(-1)
  if (last && last.kind === 'activity' && runningTurnId !== null && last.turnId === runningTurnId) {
    last.running = true
  }
  return blocks
}
