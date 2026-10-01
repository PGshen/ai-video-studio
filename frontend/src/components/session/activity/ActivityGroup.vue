<script setup lang="ts">
/**
 * 活动组（设计 §4）：一个可折叠的整体，里面是同一 turn 连续的思考与工具调用，每一行还能
 * 单独折叠。折叠状态由 `useDisclosure` 提供；默认规则见 `useDisclosure.ts`。
 */
import { computed } from 'vue'
import { ChevronDownIcon, LoaderCircleIcon } from '@lucide/vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ThinkingItem } from '@/composables/useSessionStream'
import type { ActivityGroupBlock } from '@/components/session/groupTimeline'
import { describeTool, toolStatus, type ToolStatus, type ToolView } from '@/components/session/toolPresentation'
import ActivityRow from './ActivityRow.vue'
import ThinkingBody from './ThinkingBody.vue'
import ToolBody from './ToolBody.vue'
import { THINKING_ICON, iconFor } from './toolIcons'
import { groupDefaultOpen, rowDefaultOpen, type Disclosure } from './useDisclosure'

const props = defineProps<{
  group: ActivityGroupBlock
  /** 这个组所在的 turn 已经结束：没有结果的工具显示「已中断」。 */
  turnEnded: boolean
  disclosure: Disclosure
  projectId: string | null
}>()

const toolCount = computed(() => props.group.entries.filter((e) => e.kind === 'tool_call').length)

const title = computed(() => {
  if (props.group.running) {
    return toolCount.value > 0 ? `运行中 · 第 ${toolCount.value} 次工具调用` : '思考中…'
  }
  return toolCount.value > 0 ? `${toolCount.value} 次工具调用` : '已思考'
})

const groupOpen = computed(() =>
  props.disclosure.isOpen(props.group.key, groupDefaultOpen(props.group)),
)

function firstLine(text: string): string {
  return (
    text
      .split('\n')
      .map((line) => line.trim())
      .find((line) => line !== '') ?? ''
  )
}

function thinkingView(item: ThinkingItem): { label: string; summary: string; status: ToolStatus } {
  const running = item.streaming && !props.turnEnded
  return { label: running ? '思考中' : '思考', summary: firstLine(item.text), status: running ? 'running' : 'done' }
}

const rows = computed(() =>
  props.group.entries.map((entry, index) => {
    const key = `${props.group.key}:${index}`
    if (entry.kind === 'thinking') {
      return { key, entry, icon: THINKING_ICON, ...thinkingView(entry), view: null as ToolView | null }
    }
    const view = describeTool(entry)
    return {
      key,
      entry,
      icon: iconFor(view.kind),
      label: view.label,
      summary: view.summary,
      status: toolStatus(entry, props.turnEnded),
      view,
    }
  }),
)
</script>

<template>
  <Collapsible
    :open="groupOpen"
    class="group/activity not-prose"
    @update:open="disclosure.set(group.key, $event)"
  >
    <CollapsibleTrigger
      class="text-muted-foreground hover:text-foreground flex w-full items-center gap-2 border-b py-3 text-left text-base"
      data-testid="activity-header"
    >
      <LoaderCircleIcon
        v-if="group.running"
        class="size-4 animate-spin"
      />
      <span>{{ title }}</span>
      <ChevronDownIcon
        class="size-4 transition-transform group-data-[state=closed]/activity:-rotate-90"
      />
    </CollapsibleTrigger>
    <CollapsibleContent>
      <ActivityRow
        v-for="row in rows"
        :key="row.key"
        :icon="row.icon"
        :label="row.label"
        :summary="row.summary"
        :status="row.status"
        :open="disclosure.isOpen(row.key, rowDefaultOpen(row.entry))"
        @update:open="disclosure.set(row.key, $event)"
      >
        <ThinkingBody
          v-if="row.entry.kind === 'thinking'"
          :text="row.entry.text"
        />
        <ToolBody
          v-else-if="row.view"
          :item="row.entry"
          :view="row.view"
          :project-id="projectId"
        />
      </ActivityRow>
    </CollapsibleContent>
  </Collapsible>
</template>
