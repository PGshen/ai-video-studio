<script setup lang="ts">
/**
 * 工作台右侧的快照栏（独立的第三张卡片）：标题 + 快照数 + 收起按钮 + `SnapshotTimeline`
 * （上时间线下详情）。折叠时整栏隐藏、什么都不渲染——展开入口在画布右上角（`RailToggleButton`）。
 * 折叠状态与宽度由 `WorkbenchSplit` 的分隔条管理，这里只发 `toggle`；窄屏（上下堆叠、始终展开）时
 * 不显示收起按钮，因为 `WorkbenchSplit` 在那里忽略它。选中的快照由本组件持有（折叠会卸载卡片和
 * 时间线，再展开时选中状态要还在；不能改用 `v-show`：保持挂载的卡片会让分隔条面板展不开）。
 */
import { computed, ref } from 'vue'
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
  /** 窄屏堆叠布局：栏始终展开，没有收起这回事。 */
  narrow?: boolean
}>()
defineEmits<{ (e: 'toggle'): void }>()

const { data: snapshots } = useSnapshotsQuery(() => props.projectId)
const count = computed(() => snapshots.value?.length ?? 0)
const selected = ref<string[]>([])
</script>

<template>
  <Card
    v-if="!collapsed"
    class="h-full min-h-0 min-w-60 gap-2 overflow-hidden py-3"
    data-testid="snapshot-rail"
  >
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
        v-if="!narrow"
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
        v-model:selected="selected"
        :project-id="projectId"
        :busy="busy"
      />
    </div>
  </Card>
</template>
