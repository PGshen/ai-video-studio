<script setup lang="ts">
/**
 * 选题池主体（计划 M4 T9）：视图切换（未归档/已归档）、关键词与标签筛选、卡片网格（分页），
 * 以及详情/新建/编辑/创建项目对话框的装配。筛选栏固定在顶部，只有卡片区滚动。数据来自 `useIdeasQuery`；agent 通过头脑风暴新建的卡片
 * 靠查询失效出现（T10）。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import ListPager from '@/components/ListPager.vue'
import { countProjectsByIdea } from '@/composables/ideaProjects'
import { PAGE_SIZE, pageCount, paginate } from '@/composables/pagination'
import {
  useCreateIdeaMutation,
  useIdeasQuery,
  useProjectsQuery,
  useUpdateIdeaMutation,
  type IdeasView,
} from '@/composables/queries'
import type { IdeaCreate, IdeaOut } from '@/types/api'
import CreateProjectDialog from './CreateProjectDialog.vue'
import IdeaCard from './IdeaCard.vue'
import IdeaDetailDialog from './IdeaDetailDialog.vue'
import IdeaEditDialog from './IdeaEditDialog.vue'
import { allTags, filterIdeas } from './ideaView'

const view = ref<IdeasView>(null)
const router = useRouter()
const { data: ideas, isPending, isError } = useIdeasQuery(view)
const { data: projects } = useProjectsQuery()
const projectCounts = computed(() => countProjectsByIdea(projects.value))

const query = ref('')
const tag = ref<string | null>(null)
const visible = computed(() =>
  filterIdeas(ideas.value ?? [], { query: query.value, tag: tag.value }),
)
const tags = computed(() => allTags(ideas.value ?? []))

const page = ref(1)
const totalPages = computed(() => pageCount(visible.value.length, PAGE_SIZE))
// 删除/归档后总页数可能变少，页码跟着收回来。
const currentPage = computed(() => Math.min(page.value, totalPages.value))
const pageItems = computed(() => paginate(visible.value, currentPage.value, PAGE_SIZE))
watch([view, query, tag], () => {
  page.value = 1
})

// 详情对话框按 id 取最新的卡片，操作后列表刷新时内容跟着变。
const detailId = ref<string | null>(null)
const detailOpen = computed({
  get: () => detailId.value !== null,
  set: (open) => {
    if (!open) detailId.value = null
  },
})
const detailIdea = computed(
  () => (ideas.value ?? []).find((idea) => idea.id === detailId.value) ?? null,
)

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
  detailId.value = null
  editing.value = idea
  createMutation.reset()
  updateMutation.reset()
  editOpen.value = true
}

/** 跳到项目列表，并按这张卡片筛好。 */
function openProjects(idea: IdeaOut): void {
  detailId.value = null
  void router.push({ path: '/projects', query: { idea: idea.id } })
}

function openCreateProject(idea: IdeaOut): void {
  detailId.value = null
  projectIdea.value = idea
  projectOpen.value = true
}

async function submitEdit(payload: Required<IdeaCreate>): Promise<void> {
  try {
    if (editing.value) {
      await updateMutation.mutateAsync({ id: editing.value.id, body: payload })
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
  detailId.value = null
  try {
    await updateMutation.mutateAsync({ id: idea.id, body: { status } })
  } catch (error) {
    actionError.value = describe(error)
  }
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-4">
    <div class="bg-background flex shrink-0 flex-col gap-4">
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
        <div class="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            @click="openCreate"
          >
            新建卡片
          </Button>
          <slot name="actions" />
        </div>
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
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
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
        class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3"
      >
        <IdeaCard
          v-for="idea in pageItems"
          :key="idea.id"
          :idea="idea"
          :project-count="projectCounts.get(idea.id) ?? 0"
          :busy="updateMutation.isPending.value"
          @detail="detailId = $event.id"
          @create-project="openCreateProject"
          @open-projects="openProjects"
          @restore="setStatus($event, 'idea')"
        />
      </div>
    </div>

    <ListPager
      v-model:page="page"
      :total="visible.length"
      :total-pages="totalPages"
      :current="currentPage"
    />

    <IdeaDetailDialog
      v-model:open="detailOpen"
      :idea="detailIdea"
      :project-count="detailIdea ? (projectCounts.get(detailIdea.id) ?? 0) : 0"
      :busy="updateMutation.isPending.value"
      @create-project="openCreateProject"
      @open-projects="openProjects"
      @edit="openEdit"
      @archive="setStatus($event, 'archived')"
      @restore="setStatus($event, 'idea')"
    />

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
