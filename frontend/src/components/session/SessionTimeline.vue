<script setup lang="ts">
/**
 * 时间线渲染（设计 §2、§4）：把扁平的条目流归成「活动组」，活动组走 `ActivityGroup`，其余
 * 条目（用户消息、助手文本、notice 等）走 `SessionTimelineItem`。折叠状态按会话保存。
 */
import { computed, toRef } from 'vue'
import type { TimelineItem } from '@/composables/useSessionStream'
import type { TurnOut } from '@/types/api'
import ActivityGroup from './activity/ActivityGroup.vue'
import { useDisclosure } from './activity/useDisclosure'
import { groupTimeline } from './groupTimeline'
import SessionTimelineItem from './SessionTimelineItem.vue'

const props = defineProps<{
  items: TimelineItem[]
  /** 正在排队/运行的 turn（没有则为 `null`）：决定末尾活动组是否展开、工具是否转圈。 */
  runningTurnId: string | null
  turns: ReadonlyMap<string, TurnOut>
  projectId: string | null
  sessionId: string | null
}>()

const blocks = computed(() => groupTimeline(props.items, props.runningTurnId))
const disclosure = useDisclosure(toRef(props, 'sessionId'))
</script>

<template>
  <template
    v-for="(block, index) in blocks"
    :key="index"
  >
    <ActivityGroup
      v-if="block.kind === 'activity'"
      :group="block"
      :turn-ended="block.turnId !== runningTurnId"
      :disclosure="disclosure"
      :project-id="projectId"
    />
    <SessionTimelineItem
      v-else
      :item="block"
      :project-id="projectId"
    />
  </template>
</template>
