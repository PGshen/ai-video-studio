/**
 * 快照栏组件测试共用的查询 mock：`vi.hoisted` 里放可变状态，`vi.mock('@/composables/queries')`
 * 用它构造最小的 TanStack Query 返回值（只含组件用到的字段）。
 */
import { ref, toValue, type MaybeRefOrGetter, type Ref } from 'vue'
import type { SnapshotDiffOut, SnapshotOut } from '@/types/api'

export interface QueryState {
  snapshots: Ref<SnapshotOut[]>
  diff: Ref<SnapshotDiffOut | undefined>
  diffPending: Ref<boolean>
  diffCalls: Array<{ from: string | null; to: string | null }>
  rollback: { mutateAsync: (id: string) => Promise<unknown>; calls: string[]; isPending: Ref<boolean> }
}

export function createQueryState(): QueryState {
  const calls: string[] = []
  return {
    snapshots: ref([]),
    diff: ref(undefined),
    diffPending: ref(false),
    diffCalls: [],
    rollback: {
      calls,
      isPending: ref(false),
      mutateAsync: (id: string) => {
        calls.push(id)
        return Promise.resolve()
      },
    },
  }
}

export function fakeQueries(state: QueryState) {
  return {
    useSnapshotsQuery: () => ({ data: state.snapshots }),
    useSnapshotDiffQuery: (
      _project: MaybeRefOrGetter<string>,
      from: MaybeRefOrGetter<string | null>,
      to: MaybeRefOrGetter<string | null>,
    ) => {
      // The getters are read lazily by the component; record what they resolve to on every read.
      state.diffCalls.push({ get from() { return toValue(from) }, get to() { return toValue(to) } })
      return { data: state.diff, isPending: state.diffPending }
    },
    useRollbackSnapshotMutation: () => state.rollback,
  }
}

export function snap(id: string, reason = 'turn', createdAt = '2026-10-01T14:50:00'): SnapshotOut {
  return { id, reason, turn_id: reason === 'turn' ? `${id}-turn-0000` : null, created_at: createdAt }
}
