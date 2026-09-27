<script setup lang="ts">
/**
 * 快照时间线（任务简报 T14，控制者裁定 5）：最新在前；选两个 [对比] 用
 * `@ai-elements` 的 `CodeBlock` 展示 unified diff；[回滚到此] 二次确认后
 * 调用 `useRollbackSnapshotMutation`。
 */
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { CodeBlock } from '@/components/ai-elements/code-block'
import {
  useRollbackSnapshotMutation,
  useSnapshotDiffQuery,
  useSnapshotsQuery,
} from '@/composables/queries'
import { ApiError } from '@/api/http'
import { snapshotReasonLabel } from './snapshotReason'
import { computeDiffParams, toggleSnapshotSelection } from './snapshotSelection'

const props = defineProps<{ projectId: string }>()

const { data: snapshots } = useSnapshotsQuery(() => props.projectId)
// 后端按创建时间升序返回；这里统一转成"最新在前"用于展示和 diff 参数计算。
const displaySnapshots = computed(() => [...(snapshots.value ?? [])].reverse())

const selected = ref<string[]>([])
function toggle(id: string): void {
  selected.value = toggleSnapshotSelection(selected.value, id)
}

const diffParams = computed(() => computeDiffParams(displaySnapshots.value, selected.value))
const { data: diffResult, isPending: diffPending } = useSnapshotDiffQuery(
  () => props.projectId,
  () => diffParams.value?.from ?? null,
  () => diffParams.value?.to ?? null,
)

const rollbackMutation = useRollbackSnapshotMutation(() => props.projectId)
const rollbackTarget = ref<string | null>(null)
const rollbackError = ref<string | null>(null)
// `AlertDialogAction` 底层是 reka-ui 的 `DialogClose`：点击时它自己的
// `onClick` 会把 `open` 置 false，和我们绑在同一个按钮上的 `@click`
// 一起触发——谁先谁后不由我们控制（审查/走查发现：如果它先跑，我们
// `@update:open` 里的 `rollbackTarget.value = null` 就会抢在
// `confirmRollback` 读到目标 id 之前清空它，回滚请求整个不会发出去，
// 且没有任何报错，非常隐蔽）。用一个不受 `update:open` 影响的普通变量
// 单独存一份要回滚的 id，彻底绕开这个事件顺序竞态。
let pendingRollbackId: string | null = null

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'agent 运行中，无法回滚'
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

function openRollbackDialog(id: string): void {
  pendingRollbackId = id
  rollbackTarget.value = id
}

async function confirmRollback(): Promise<void> {
  const id = pendingRollbackId
  if (!id) return
  rollbackError.value = null
  try {
    await rollbackMutation.mutateAsync(id)
    pendingRollbackId = null
    rollbackTarget.value = null
  } catch (error) {
    rollbackError.value = describeError(error)
  }
}
</script>

<template>
  <div class="flex min-h-0 flex-col gap-2 border-t pt-3">
    <div class="flex items-center justify-between">
      <p class="text-sm font-medium">
        快照时间线
      </p>
      <p class="text-muted-foreground text-xs">
        选中两个快照可以对比
      </p>
    </div>

    <ul class="flex max-h-40 flex-col gap-1 overflow-y-auto text-sm">
      <li
        v-for="snapshot in displaySnapshots"
        :key="snapshot.id"
        class="flex items-center justify-between gap-2 rounded px-2 py-1"
        :class="selected.includes(snapshot.id) ? 'bg-primary/10' : 'hover:bg-muted'"
      >
        <button
          type="button"
          class="flex min-w-0 flex-1 items-center gap-2 text-left"
          @click="toggle(snapshot.id)"
        >
          <span class="font-medium">{{ snapshotReasonLabel(snapshot.reason) }}</span>
          <span
            v-if="snapshot.turn_id"
            class="text-muted-foreground text-xs"
          >turn {{ snapshot.turn_id.slice(0, 8) }}</span>
          <span class="text-muted-foreground ml-auto shrink-0 text-xs">{{ snapshot.created_at }}</span>
        </button>
        <Button
          size="sm"
          variant="outline"
          @click="openRollbackDialog(snapshot.id)"
        >
          回滚到此
        </Button>
      </li>
      <li
        v-if="displaySnapshots.length === 0"
        class="text-muted-foreground px-2 py-1"
      >
        还没有快照
      </li>
    </ul>

    <div v-if="diffParams">
      <p
        v-if="diffPending"
        class="text-muted-foreground text-xs"
      >
        对比中…
      </p>
      <template v-else-if="diffResult">
        <div class="text-xs">
          <p v-if="diffResult.added.length > 0">
            新增：{{ diffResult.added.join('、') }}
          </p>
          <p v-if="diffResult.removed.length > 0">
            删除：{{ diffResult.removed.join('、') }}
          </p>
        </div>
        <div
          v-for="file in diffResult.modified"
          :key="file.path"
          class="mt-2"
        >
          <p class="text-xs font-medium">
            {{ file.path }}
          </p>
          <CodeBlock
            v-if="file.text_diff !== null"
            :code="file.text_diff"
            language="diff"
          />
          <p
            v-else
            class="text-muted-foreground text-xs"
          >
            二进制文件，不生成 diff
          </p>
        </div>
      </template>
    </div>

    <p
      v-if="rollbackError"
      class="text-destructive text-xs"
    >
      {{ rollbackError }}
    </p>

    <AlertDialog
      :open="rollbackTarget !== null"
      @update:open="(open) => { if (!open) rollbackTarget = null }"
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>回滚到这个快照？</AlertDialogTitle>
          <AlertDialogDescription>
            工作区文件会恢复到这个快照的状态；这个操作本身会新建一条快照，可以再回滚回来。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction @click="confirmRollback">
            确认回滚
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
