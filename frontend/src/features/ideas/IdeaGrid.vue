<script setup lang="ts">
/**
 * 选题池主体（计划 M4 T9）：视图切换（未归档/已归档）、关键词与标签筛选、卡片网格，以及
 * 新建/编辑/创建项目对话框的装配。数据来自 `useIdeasQuery`；agent 通过头脑风暴新建的卡片
 * 靠查询失效出现（T10）。
 */
import { computed, ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  useCreateIdeaMutation,
  useIdeasQuery,
  useUpdateIdeaMutation,
  type IdeasView,
} from '@/composables/queries'
import type { IdeaCreate, IdeaOut } from '@/types/api'
import CreateProjectDialog from './CreateProjectDialog.vue'
import IdeaCard from './IdeaCard.vue'
import IdeaEditDialog from './IdeaEditDialog.vue'
import { allTags, filterIdeas } from './ideaView'

const view = ref<IdeasView>(null)
const { data: ideas, isPending, isError } = useIdeasQuery(view)

const query = ref('')
const tag = ref<string | null>(null)
const visible = computed(() =>
  filterIdeas(ideas.value ?? [], { query: query.value, tag: tag.value }),
)
const tags = computed(() => allTags(ideas.value ?? []))

const createMutation = useCreateIdeaMutation()
const updateMutation = useUpdateIdeaMutation()
const actionError = ref<string | null>(null)

const editOpen = ref(false)
const editing = ref<IdeaOut | null>(null)
const projectOpen = ref(false)
const projectIdea = ref<IdeaOut | null>(null)

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function openCreate(): void {
  editing.value = null
  createMutation.reset()
  updateMutation.reset()
  editOpen.value = true
}

function openEdit(idea: IdeaOut): void {
  editing.value = idea
  createMutation.reset()
  updateMutation.reset()
  editOpen.value = true
}

function openCreateProject(idea: IdeaOut): void {
  projectIdea.value = idea
  projectOpen.value = true
}

async function submitEdit(payload: Required<IdeaCreate>): Promise<void> {
  try {
    if (editing.value) {
      // 已创建项目的卡片标题不可改（后端会拒绝，即使标题没变）。
      const { title, ...rest } = payload
      const body = editing.value.status === 'picked' ? rest : { title, ...rest }
      await updateMutation.mutateAsync({ id: editing.value.id, body })
    } else {
      await createMutation.mutateAsync(payload)
    }
    editOpen.value = false
  } catch {
    // 错误显示在对话框里（`editError`）。
  }
}

const editError = computed(() => {
  const error = editing.value ? updateMutation.error.value : createMutation.error.value
  return error ? describe(error) : null
})
const editPending = computed(() =>
  editing.value ? updateMutation.isPending.value : createMutation.isPending.value,
)

async function setStatus(idea: IdeaOut, status: 'idea' | 'archived'): Promise<void> {
  actionError.value = null
  try {
    await updateMutation.mutateAsync({ id: idea.id, body: { status } })
  } catch (error) {
    actionError.value = describe(error)
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex gap-1">
        <Button
          size="sm"
          :variant="view === null ? 'default' : 'outline'"
          @click="view = null"
        >
          未归档
        </Button>
        <Button
          size="sm"
          :variant="view === 'archived' ? 'default' : 'outline'"
          @click="view = 'archived'"
        >
          已归档
        </Button>
      </div>
      <Input
        v-model="query"
        class="max-w-xs"
        placeholder="搜索标题、卖点、标签"
      />
      <Button
        class="ml-auto"
        size="sm"
        variant="outline"
        @click="openCreate"
      >
        新建卡片
      </Button>
    </div>

    <div
      v-if="tags.length"
      class="flex flex-wrap items-center gap-1"
    >
      <span class="text-muted-foreground text-xs">标签：</span>
      <Badge
        v-for="t in tags"
        :key="t"
        class="cursor-pointer"
        :variant="tag === t ? 'default' : 'outline'"
        @click="tag = tag === t ? null : t"
      >
        {{ t }}
      </Badge>
    </div>

    <p
      v-if="actionError"
      class="text-destructive text-sm"
    >
      操作失败：{{ actionError }}
    </p>
    <p
      v-if="isPending"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
    <p
      v-else-if="isError"
      class="text-destructive text-sm"
    >
      选题池加载失败。
    </p>
    <p
      v-else-if="visible.length === 0"
      class="text-muted-foreground text-sm"
    >
      {{
        (ideas?.length ?? 0) > 0
          ? '没有符合筛选条件的卡片。'
          : view === 'archived'
            ? '没有归档的卡片。'
            : '选题池还是空的：和头脑风暴助手聊聊，或者手动新建一张卡片。'
      }}
    </p>
    <div
      v-else
      class="grid gap-3 md:grid-cols-2 xl:grid-cols-3"
    >
      <IdeaCard
        v-for="idea in visible"
        :key="idea.id"
        :idea="idea"
        :busy="updateMutation.isPending.value"
        @create-project="openCreateProject"
        @edit="openEdit"
        @archive="setStatus($event, 'archived')"
        @restore="setStatus($event, 'idea')"
      />
    </div>

    <IdeaEditDialog
      v-model:open="editOpen"
      :idea="editing"
      :pending="editPending"
      :error="editError"
      @submit="submitEdit"
    />
    <CreateProjectDialog
      v-model:open="projectOpen"
      :idea="projectIdea"
    />
  </div>
</template>
