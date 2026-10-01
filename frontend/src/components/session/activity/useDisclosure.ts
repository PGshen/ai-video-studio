/**
 * 活动组 / 行的折叠状态（设计 §4.2）：默认值由规则决定，用户手动切换过的以用户为准。
 * 状态只存在组件树内（不入 store），切换会话时清空，避免新会话继承旧会话的展开状态。
 */
import { reactive, watch, type Ref } from 'vue'
import type { ThinkingItem, ToolCallItem } from '@/composables/useSessionStream'
import type { ActivityGroupBlock } from '@/components/session/groupTimeline'

export function useDisclosure(sessionId: Ref<string | null>) {
  const overrides = reactive(new Map<string, boolean>())
  watch(sessionId, () => overrides.clear())
  return {
    /** 用户切换过就用用户的值，否则用 `fallback`（规则给出的默认值）。 */
    isOpen: (key: string, fallback: boolean): boolean => overrides.get(key) ?? fallback,
    set: (key: string, open: boolean): void => {
      overrides.set(key, open)
    },
  }
}

export type Disclosure = ReturnType<typeof useDisclosure>

/** 运行中的末尾组默认展开；turn 结束或后面出现文本后 `running` 变假，自动折叠。 */
export function groupDefaultOpen(group: ActivityGroupBlock): boolean {
  return group.running
}

/** 出错的工具行默认展开，其余默认折叠。 */
export function rowDefaultOpen(entry: ThinkingItem | ToolCallItem): boolean {
  return entry.kind === 'tool_call' && entry.result?.isError === true
}
