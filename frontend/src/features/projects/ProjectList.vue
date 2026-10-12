<script setup lang="ts">
/**
 * 项目列表：关键词/阶段/状态/选题筛选 + 卡片网格（分页）。「新建项目」直接创建自由项目（free-mode 设计
 * §6.1）；多阶段项目仍从选题池的卡片创建。
 * 筛选栏固定在顶部，只有卡片区滚动；卡片上的选题信息来自全部选题（按项目的 `idea_id` 关联）。
 * 选题池的「打开项目」带 `?idea=<选题 id>` 跳过来，URL 里的这个参数就是「按选题筛选」的状态。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import ListPager from '@/components/ListPager.vue'
import { useAllIdeasQuery, useProjectsQuery } from '@/composables/queries'
import { PAGE_SIZE, pageCount, paginate } from '@/composables/pagination'
import { STAGE_TITLES } from '@/composables/stageTitles'
import NewFreeProjectDialog from './NewFreeProjectDialog.vue'
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
const creating = ref(false)
const stage = ref<string | null>(null)
const status = ref<StatusFilter>('all')

const STATUS_OPTIONS: ReadonlyArray<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'active', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'abandoned', label: '已废弃' },
]
/** 下拉单选项的值必须是字符串，「全部阶段」用这个哨兵值，对应 `stage = null`。 */
const ALL_STAGES = '__all__'
const STAGE_OPTIONS = [
  { value: ALL_STAGES, label: '全部阶段' },
  ...Object.entries(STAGE_TITLES).map(([value, label]) => ({ value, label })),
]
const statusLabel = computed(() => STATUS_OPTIONS.find((o) => o.value === status.value)?.label ?? '')
const stageLabel = computed(() => STAGE_OPTIONS.find((o) => o.value === (stage.value ?? ALL_STAGES))?.label ?? '')

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
        size="sm"
        data-testid="new-project"
        @click="creating = true"
      >
        新建项目
      </Button>
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
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button
            size="sm"
            variant="outline"
            data-testid="status-filter"
          >
            {{ statusLabel }}
            <ChevronDown />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuRadioGroup
            :model-value="status"
            @update:model-value="status = $event as StatusFilter"
          >
            <DropdownMenuRadioItem
              v-for="option in STATUS_OPTIONS"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button
            size="sm"
            variant="outline"
            data-testid="stage-filter"
          >
            {{ stageLabel }}
            <ChevronDown />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuRadioGroup
            :model-value="stage ?? ALL_STAGES"
            @update:model-value="stage = $event === ALL_STAGES ? null : String($event)"
          >
            <DropdownMenuRadioItem
              v-for="option in STAGE_OPTIONS"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
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
            : '还没有项目：新建一个项目，或从「选题」的卡片创建。'
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
    <NewFreeProjectDialog v-model:open="creating" />
  </div>
</template>
