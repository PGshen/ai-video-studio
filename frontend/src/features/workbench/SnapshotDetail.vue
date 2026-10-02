<script setup lang="ts">
/**
 * 快照栏下半部分：所选快照的详情（标题、「回滚到此」、变更文件与 diff）。
 * 选 1 个对比它与上一个快照，选 2 个对比这两个（规则见 `resolveDiffTarget`）；
 * 「回滚到此」只在恰好选中一个时出现，二次确认后调用 `useRollbackSnapshotMutation`。
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
import { useRollbackSnapshotMutation, useSnapshotDiffQuery } from '@/composables/queries'
import { ApiError } from '@/api/http'
import { snapshotReasonLabel } from '@/components/session/snapshotReason'
import type { SnapshotOut } from '@/types/api'
import { canRollback, resolveDiffTarget } from './snapshotSelection'
import { formatSnapshotTime } from './snapshotTime'

const props = defineProps<{
  projectId: string
  /** 项目是否忙；忙时只能看，不能回滚（`combineBusy` 的结果，见 `ProjectWorkbenchPage`）。 */
  busy: boolean
  /** 最新在前。 */
  snapshots: SnapshotOut[]
  selected: string[]
}>()

const target = computed(() => resolveDiffTarget(props.snapshots, props.selected))
const byId = (id: string): SnapshotOut | undefined => props.snapshots.find((s) => s.id === id)
const label = (snapshot: SnapshotOut | undefined): string =>
  snapshot ? `${snapshotReasonLabel(snapshot.reason)} ${formatSnapshotTime(snapshot.created_at)}` : ''

const present = computed(() => props.selected.filter((id) => byId(id)))
/** 恰好选中一个时的那个快照（回滚的目标）。 */
const single = computed(() => (present.value.length === 1 ? byId(present.value[0]!) : undefined))
const title = computed(() => {
  if (single.value) return label(single.value)
  if (target.value.kind === 'diff') return `对比 ${label(byId(target.value.from))} → ${label(byId(target.value.to))}`
  return ''
})

const { data: diffResult, isPending: diffPending } = useSnapshotDiffQuery(
  () => props.projectId,
  () => (target.value.kind === 'diff' ? target.value.from : null),
  () => (target.value.kind === 'diff' ? target.value.to : null),
)
const unchanged = computed(
  () =>
    diffResult.value !== undefined &&
    diffResult.value.added.length === 0 &&
    diffResult.value.removed.length === 0 &&
    diffResult.value.modified.length === 0,
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
  <div
    class="flex min-h-0 flex-col gap-2 text-sm"
    data-testid="snapshot-detail"
  >
    <p
      v-if="target.kind === 'none'"
      class="text-muted-foreground text-xs"
    >
      选择一个快照查看详情
    </p>
    <template v-else>
      <div class="flex items-center justify-between gap-2">
        <p class="min-w-0 font-medium break-words">
          {{ title || '初始快照' }}
        </p>
        <Button
          v-if="single"
          size="sm"
          variant="outline"
          class="shrink-0"
          data-testid="rollback-button"
          :disabled="!rollbackEnabled"
          :title="busy ? 'agent 运行中' : undefined"
          @click="openRollbackDialog(single.id)"
        >
          回滚到此
        </Button>
      </div>

      <p
        v-if="target.kind === 'initial'"
        class="text-muted-foreground text-xs"
      >
        初始快照，没有更早的版本可以对比
      </p>
      <template v-else>
        <p
          v-if="diffPending"
          class="text-muted-foreground text-xs"
        >
          对比中…
        </p>
        <template v-else-if="diffResult">
          <p
            v-if="unchanged"
            class="text-muted-foreground text-xs"
          >
            与上一个快照相比没有变化
          </p>
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
      </template>
    </template>

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
