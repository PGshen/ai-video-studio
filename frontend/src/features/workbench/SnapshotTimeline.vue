<script setup lang="ts">
/**
 * 快照栏（时间线 + 详情，上下布局）：上半部分是时间线（最新在前，点选；最多选两个），
 * 下半部分 `SnapshotDetail` 显示所选快照的详情与「回滚到此」。
 * 选择规则见 `snapshotSelection.ts`；回滚按钮的禁用规则见 `canRollback`。
 */
import { computed } from 'vue'
import { useSnapshotsQuery } from '@/composables/queries'
import { snapshotReasonLabel } from '@/components/session/snapshotReason'
import SnapshotDetail from './SnapshotDetail.vue'
import { toggleSnapshotSelection } from './snapshotSelection'
import { formatSnapshotTime } from './snapshotTime'

const props = defineProps<{
  projectId: string
  /**
   * 项目是否忙（`ProjectWorkbenchPage` 传入的 `combineBusy` 结果）。忙时「回滚到此」禁用；
   * 选中快照看详情不受影响。
   */
  busy: boolean
}>()

const { data: snapshots } = useSnapshotsQuery(() => props.projectId)
// 后端按创建时间升序返回；这里统一转成"最新在前"用于展示和 diff 参数计算。
const displaySnapshots = computed(() => [...(snapshots.value ?? [])].reverse())

/** 选中的快照 id（最多两个）；由 `SnapshotRail` 持有以便折叠、展开后还在，单独使用时是本地状态。 */
const selected = defineModel<string[]>('selected', { default: () => [] })
function toggle(id: string): void {
  selected.value = toggleSnapshotSelection(selected.value, id)
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <p class="text-muted-foreground text-xs">
      {{ busy ? 'agent 运行中，暂不能回滚' : '选中两个快照可以对比' }}
    </p>

    <ul
      class="flex max-h-[45%] min-h-24 shrink-0 flex-col gap-1 overflow-y-auto text-sm"
      data-testid="snapshot-list"
    >
      <li
        v-for="snapshot in displaySnapshots"
        :key="snapshot.id"
        data-testid="snapshot-item"
        class="rounded"
        :class="selected.includes(snapshot.id) ? 'bg-primary/10' : 'hover:bg-muted'"
      >
        <button
          type="button"
          class="flex w-full min-w-0 flex-col items-start gap-0.5 px-2 py-1 text-left"
          @click="toggle(snapshot.id)"
        >
          <span class="font-medium">{{ snapshotReasonLabel(snapshot.reason) }}</span>
          <span class="text-muted-foreground text-xs">
            {{ formatSnapshotTime(snapshot.created_at) }}<template v-if="snapshot.turn_id"> · turn {{ snapshot.turn_id.slice(0, 8) }}</template>
          </span>
        </button>
      </li>
      <li
        v-if="displaySnapshots.length === 0"
        class="text-muted-foreground px-2 py-1"
      >
        还没有快照
      </li>
    </ul>

    <div class="min-h-0 flex-1 overflow-y-auto border-t pt-3">
      <SnapshotDetail
        :project-id="projectId"
        :busy="busy"
        :snapshots="displaySnapshots"
        :selected="selected"
      />
    </div>
  </div>
</template>
