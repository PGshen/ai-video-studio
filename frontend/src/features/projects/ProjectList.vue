<script setup lang="ts">
/**
 * 项目列表：关键词/阶段/状态/选题筛选 + 卡片网格（分页）。项目只能从选题池的卡片创建，这里没有新建入口。
 * 筛选栏固定在顶部，只有卡片区滚动；卡片上的选题信息来自全部选题（按项目的 `idea_id` 关联）。
 * 选题池的「打开项目」带 `?idea=<选题 id>` 跳过来，URL 里的这个参数就是「按选题筛选」的状态。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import ListPager from '@/components/ListPager.vue'
import { useAllIdeasQuery, useProjectsQuery } from '@/composables/queries'
import { PAGE_SIZE, pageCount, paginate } from '@/composables/pagination'
import { STAGE_TITLES } from '@/composables/stageTitles'
import ProjectCard from './ProjectCard.vue'
import { filterProjects, ideasById, type StatusFilter } from './projectView'

const { data: projects, isPending, isError } = useProjectsQuery()
const { data: ideas } = useAllIdeasQuery()
const ideaOf = computed(() => ideasById(ideas.value))

const route = useRoute()
const router = useRouter()
const ideaId = computed(() => {
  const value = route.query.idea
  return typeof value === 'string' && value !== '' ? value : null
})
const ideaTitle = computed(() => (ideaId.value ? ideaOf.value.get(ideaId.value)?.title ?? '该选题' : null))

function clearIdea(): void {
  void router.replace({ path: route.path, query: {} })
}

const query = ref('')
const stage = ref<string | null>(null)
const status = ref<StatusFilter>('all')

const STATUS_OPTIONS: ReadonlyArray<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'active', label: '进行中' },
  { value: 'done', label: '已完成' },
]
const STAGE_OPTIONS = [
  { value: null, label: '全部阶段' },
  ...Object.entries(STAGE_TITLES).map(([value, label]) => ({ value, label })),
]

const visible = computed(() =>
  filterProjects(projects.value ?? [], ideaOf.value, {
    query: query.value,
    stage: stage.value,
    status: status.value,
    ideaId: ideaId.value,
  }),
)

const page = ref(1)
const totalPages = computed(() => pageCount(visible.value.length, PAGE_SIZE))
const currentPage = computed(() => Math.min(page.value, totalPages.value))
const pageItems = computed(() => paginate(visible.value, currentPage.value, PAGE_SIZE))
watch([query, stage, status, ideaId], () => {
  page.value = 1
})
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">
    <div class="flex shrink-0 flex-wrap items-center gap-2">
      <Button
        v-if="ideaTitle"
        size="sm"
        variant="secondary"
        class="max-w-xs"
        data-testid="idea-filter"
        title="清除选题筛选"
        @click="clearIdea"
      >
        <span class="truncate">选题：{{ ideaTitle }}</span>
        <span aria-hidden="true">×</span>
      </Button>
      <div class="flex gap-1">
        <Button
          v-for="option in STATUS_OPTIONS"
          :key="option.value"
          size="sm"
          :variant="status === option.value ? 'default' : 'outline'"
          @click="status = option.value"
        >
          {{ option.label }}
        </Button>
      </div>
      <div class="flex gap-1">
        <Button
          v-for="option in STAGE_OPTIONS"
          :key="option.value ?? 'all'"
          size="sm"
          :variant="stage === option.value ? 'default' : 'outline'"
          @click="stage = option.value"
        >
          {{ option.label }}
        </Button>
      </div>
      <Input
        v-model="query"
        class="max-w-xs"
        placeholder="搜索标题、卖点、标签"
      />
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
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
        项目列表加载失败。
      </p>
      <p
        v-else-if="visible.length === 0"
        class="text-muted-foreground text-sm"
      >
        {{
          (projects?.length ?? 0) > 0
            ? '没有符合筛选条件的项目。'
            : '还没有项目：在「选题」里选一张卡片，点「创建项目」。'
        }}
      </p>
      <div
        v-else
        class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3"
      >
        <ProjectCard
          v-for="project in pageItems"
          :key="project.id"
          :project="project"
          :idea="(project.idea_id && ideaOf.get(project.idea_id)) || null"
        />
      </div>
    </div>

    <ListPager
      v-model:page="page"
      :total="visible.length"
      :total-pages="totalPages"
      :current="currentPage"
    />
  </div>
</template>
