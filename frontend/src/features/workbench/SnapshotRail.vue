<script setup lang="ts">
/**
 * 工作台右侧的快照栏（独立的第三张卡片）：展开时是标题 + 快照数 + 收起按钮 + `SnapshotTimeline`
 * （上时间线下详情），折叠时只剩图标和快照数的窄条，点击展开。折叠状态与宽度由
 * `WorkbenchSplit` 的分隔条管理，这里只发 `toggle`。
 */
import { computed } from 'vue'
import { HistoryIcon, PanelRightCloseIcon } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useSnapshotsQuery } from '@/composables/queries'
import SnapshotTimeline from './SnapshotTimeline.vue'

const props = defineProps<{
  projectId: string
  /** 项目是否忙，原样传给 `SnapshotTimeline`。 */
  busy: boolean
  collapsed: boolean
}>()
defineEmits<{ (e: 'toggle'): void }>()

const { data: snapshots } = useSnapshotsQuery(() => props.projectId)
const count = computed(() => snapshots.value?.length ?? 0)
</script>

<template>
  <Card
    class="h-full min-h-0 gap-2 overflow-hidden py-3"
    data-testid="snapshot-rail"
  >
    <div
      v-if="collapsed"
      class="flex flex-col items-center gap-2"
    >
      <Button
        variant="ghost"
        size="icon-sm"
        title="展开快照栏"
        aria-label="展开快照栏"
        data-testid="toggle-snapshots"
        @click="$emit('toggle')"
      >
        <HistoryIcon />
      </Button>
      <span
        class="text-muted-foreground text-xs"
        data-testid="snapshot-count"
      >{{ count }}</span>
    </div>
    <template v-else>
      <div class="flex shrink-0 items-center justify-between gap-2 px-4">
        <div class="flex min-w-0 items-center gap-2 text-sm font-medium">
          <HistoryIcon class="size-4 shrink-0" />
          <span class="truncate">快照</span>
          <span
            class="text-muted-foreground text-xs font-normal"
            data-testid="snapshot-count"
          >{{ count }}</span>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          title="收起快照栏"
          aria-label="收起快照栏"
          data-testid="toggle-snapshots"
          @click="$emit('toggle')"
        >
          <PanelRightCloseIcon />
        </Button>
      </div>
      <div class="flex min-h-0 flex-1 flex-col px-4">
        <SnapshotTimeline
          :project-id="projectId"
          :busy="busy"
        />
      </div>
    </template>
  </Card>
</template>
