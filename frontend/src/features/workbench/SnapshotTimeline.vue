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
import { canRollback, computeDiffParams, toggleSnapshotSelection } from './snapshotSelection'

const props = defineProps<{
  projectId: string
  /**
   * 项目是否忙（`ProjectWorkbenchPage` 传入的 `combineBusy` 结果，见该
   * 页面的文档注释）。T14 审查修复：[回滚到此] 原来一直可点，agent 运行
   * 中点开二次确认弹窗、提交时才被后端 409 拒绝；现在提前禁用。
   * [对比]（选中快照看 diff）不受影响，busy 时也能看。
   */
  busy: boolean
}>()

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
const rollbackEnabled = computed(() => canRollback(props.busy, rollbackMutation.isPending.value))
const rollbackTarget = ref<string | null>(null)
const rollbackError = ref<string | null>(null)
// `AlertDialogAction` 底层是 reka-ui 的 `DialogClose`：点击时它自己的
// `onClick` 会把 `open` 置 false，和我们绑在同一个按钮上的 `@click`
// 一起触发——谁先谁后不由我们控制（审查/走查发现：如果它先跑，我们
// `@update:open` 里的 `rollbackTarget.value = null` 就会抢在
// `confirmRollback` 读到目标 id 之前清空它，回滚请求整个不会发出去，
// 且没有任何报错，非常隐蔽）。这里用一个**普通变量**（不是 `ref`，故意
// 不接入 Vue 响应式系统）单独存一份要回滚的 id：正因为它不是响应式的，
// `<AlertDialog @update:open>` 清空 `rollbackTarget`（一个 ref）这件事
// 完全触碰不到它，`confirmRollback` 读到的永远是 `openRollbackDialog`
// 写入时的那份值，彻底绕开这个事件顺序竞态。
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
    rollbackTarget.value = null
  } catch (error) {
    rollbackError.value = describeError(error)
  } finally {
    // 无论成功还是失败都清掉：这个变量只代表"这一次点击要回滚到哪个
    // id"，请求已经发出去过一次之后就不该再被下一次误读到（哪怕失败，
    // 对话框此时也已经因为 `AlertDialogAction` 自身的 `DialogClose`
    // 行为关掉了——见上面 `pendingRollbackId` 声明处的注释——重新点
    // [回滚到此] 会通过 `openRollbackDialog` 重新赋值）。
    pendingRollbackId = null
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
        {{ busy ? 'agent 运行中，暂不能回滚' : '选中两个快照可以对比' }}
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
          :disabled="!rollbackEnabled"
          :title="busy ? 'agent 运行中' : undefined"
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
          <AlertDialogCancel
            :disabled="rollbackMutation.isPending.value"
            @click="pendingRollbackId = null"
          >
            取消
          </AlertDialogCancel>
          <AlertDialogAction
            :disabled="!rollbackEnabled"
            @click="confirmRollback"
          >
            确认回滚
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
