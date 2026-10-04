<script setup lang="ts">
/**
 * 风格库列表（计划 style-library T6）：顶部筛选栏（关键词、分类、仅看默认）+「新建风格」，
 * 卡片网格 + 分页。点卡片或编辑按钮只改 URL query（`?style=<id>&mode=view|edit`），抽屉由页面
 * 根据 query 打开（T7）。数据来自 `useStylesQuery`；筛选、排序、分页都在前端做。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { errorMessage } from '@/api/http'
import ListPager from '@/components/ListPager.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PAGE_SIZE, pageCount, paginate } from '@/composables/pagination'
import { useCreateStyleMutation, useStylesQuery } from '@/composables/queries'
import type { StyleSummaryOut } from '@/types/api'
import StyleCard from './StyleCard.vue'
import { allCategories, filterStyles, sortStyles } from './styleView'

const route = useRoute()
const router = useRouter()
const { data: styles, isPending, isError } = useStylesQuery()
const createMutation = useCreateStyleMutation()

const keyword = ref('')
const category = ref<string | null>(null)
const onlyDefault = ref(false)
const categories = computed(() => allCategories(styles.value ?? []))
const visible = computed(() =>
  sortStyles(
    filterStyles(styles.value ?? [], {
      keyword: keyword.value,
      category: category.value,
      onlyDefault: onlyDefault.value,
    }),
  ),
)

const page = ref(1)
const totalPages = computed(() => pageCount(visible.value.length, PAGE_SIZE))
// 删除风格后总页数可能变少，页码跟着收回来。
const currentPage = computed(() => Math.min(page.value, totalPages.value))
const pageItems = computed(() => paginate(visible.value, currentPage.value, PAGE_SIZE))
watch([keyword, category, onlyDefault], () => {
  page.value = 1
})

function openDrawer(id: string, mode: 'view' | 'edit'): void {
  void router.push({ query: { ...route.query, style: id, mode } })
}

const actionError = ref<string | null>(null)
async function createStyle(): Promise<void> {
  actionError.value = null
  try {
    const draft = await createMutation.mutateAsync()
    openDrawer(draft.id, 'edit')
  } catch (error) {
    actionError.value = errorMessage(error)
  }
}

function open(item: StyleSummaryOut): void {
  openDrawer(item.id, 'view')
}
function edit(item: StyleSummaryOut): void {
  openDrawer(item.id, 'edit')
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col gap-4">
    <div class="bg-background flex shrink-0 flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2">
        <Input
          v-model="keyword"
          class="max-w-xs"
          placeholder="搜索名称、简介、分类"
          data-testid="style-search"
        />
        <Button
          size="sm"
          :variant="onlyDefault ? 'default' : 'outline'"
          data-testid="style-only-default"
          @click="onlyDefault = !onlyDefault"
        >
          仅看默认
        </Button>
        <Button
          size="sm"
          class="ml-auto"
          :disabled="createMutation.isPending.value"
          data-testid="new-style"
          @click="createStyle"
        >
          新建风格
        </Button>
      </div>

      <div
        v-if="categories.length"
        class="flex flex-wrap items-center gap-1"
      >
        <span class="text-muted-foreground text-xs">分类：</span>
        <Badge
          v-for="c in categories"
          :key="c"
          class="cursor-pointer"
          :variant="category === c ? 'default' : 'outline'"
          :data-testid="`style-category-${c}`"
          @click="category = category === c ? null : c"
        >
          {{ c }}
        </Badge>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <p
        v-if="actionError"
        class="text-destructive text-sm"
        data-testid="style-action-error"
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
        风格库加载失败。
      </p>
      <p
        v-else-if="visible.length === 0"
        class="text-muted-foreground text-sm"
        data-testid="style-empty"
      >
        {{
          (styles?.length ?? 0) > 0
            ? '没有符合筛选条件的风格。'
            : '风格库还是空的：点「新建风格」，或导入旧项目的风格。'
        }}
      </p>
      <div
        v-else
        class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3"
      >
        <StyleCard
          v-for="item in pageItems"
          :key="item.id"
          :item="item"
          @open="open"
          @edit="edit"
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
