<script setup lang="ts">
/**
 * 一个项目的摘要卡片：标题、当前阶段和状态、关联选题的卖点/标签/总分。整张卡片是进入工作台的链接，
 * 右上角的「⋯」菜单用来设置项目状态（它是链接的兄弟节点，点它不会跳转）。
 * 项目没有关联选题时（旧数据）只显示标题和阶段。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import ProjectStatusMenu from '@/components/ProjectStatusMenu.vue'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { STAGE_TITLES } from '@/composables/stageTitles'
import { ideaTotal } from '@/composables/ideaScores'
import type { IdeaOut, ProjectOut } from '@/types/api'
import { projectStatus, statusText } from './projectView'

/** 摘要里最多显示几个标签，其余折叠成「+N」。 */
const VISIBLE_TAGS = 3

const props = defineProps<{ project: ProjectOut; idea: IdeaOut | null }>()

const status = computed(() => projectStatus(props.project))
const tags = computed(() => props.idea?.tags ?? [])
const shownTags = computed(() => tags.value.slice(0, VISIBLE_TAGS))
const hiddenTags = computed(() => tags.value.length - shownTags.value.length)
const total = computed(() => (props.idea ? ideaTotal(props.idea.scores) : { sum: 0, count: 0 }))
const statusDate = computed(() => {
  const iso = status.value === 'abandoned' ? props.project.abandoned_at : props.project.completed_at
  if (!iso || status.value === 'active') return null
  const label = status.value === 'abandoned' ? '废弃于' : '完成于'
  return `${label} ${new Date(iso).toLocaleDateString('zh-CN')}`
})
</script>

<template>
  <div class="relative">
    <RouterLink
      :to="`/projects/${project.id}/${project.current_stage}`"
      class="block h-full"
      :data-testid="`project-card-${project.id}`"
    >
      <Card
        class="hover:border-primary h-full transition-colors"
        :class="{ 'opacity-60': status === 'abandoned' }"
      >
        <CardHeader class="gap-2">
          <CardTitle class="line-clamp-2 pr-7 text-base leading-snug">
            {{ project.title }}
          </CardTitle>
          <div class="flex items-center gap-1">
            <Badge variant="secondary">
              {{ STAGE_TITLES[project.current_stage] ?? project.current_stage }}
            </Badge>
            <Badge :variant="status === 'completed' ? 'default' : 'outline'">
              {{ statusText(status) }}
            </Badge>
          </div>
          <p
            v-if="idea?.pitch"
            class="text-muted-foreground line-clamp-3 text-sm"
          >
            {{ idea.pitch }}
          </p>
          <p
            v-else-if="!idea"
            class="text-muted-foreground text-sm"
          >
            未关联选题
          </p>
        </CardHeader>

        <CardContent
          v-if="tags.length"
          class="flex flex-1 flex-wrap content-start items-center gap-1"
        >
          <Badge
            v-for="tag in shownTags"
            :key="tag"
            variant="outline"
          >
            {{ tag }}
          </Badge>
          <span
            v-if="hiddenTags > 0"
            class="text-muted-foreground text-xs"
          >
            +{{ hiddenTags }}
          </span>
        </CardContent>

        <CardFooter
          v-if="total.count || statusDate"
          class="text-muted-foreground flex items-center justify-between text-xs"
        >
          <span v-if="total.count">选题评分 {{ total.sum }}/{{ total.count * 5 }}</span>
          <span
            v-if="statusDate"
            class="ml-auto"
          >
            {{ statusDate }}
          </span>
        </CardFooter>
      </Card>
    </RouterLink>
    <div class="absolute top-3 right-3">
      <ProjectStatusMenu
        compact
        :project-id="project.id"
        :status="status"
      />
    </div>
  </div>
</template>
