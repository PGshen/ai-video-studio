<script setup lang="ts">
/**
 * 一个项目的摘要卡片：标题、当前阶段和状态、关联选题的卖点/标签/总分。整张卡片是进入工作台的链接。
 * 项目没有关联选题时（旧数据）只显示标题和阶段。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
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
const completedDate = computed(() =>
  props.project.completed_at
    ? new Date(props.project.completed_at).toLocaleDateString('zh-CN')
    : null,
)
</script>

<template>
  <RouterLink
    :to="`/projects/${project.id}/${project.current_stage}`"
    class="block"
    :data-testid="`project-card-${project.id}`"
  >
    <Card class="hover:border-primary h-full transition-colors">
      <CardHeader class="gap-2">
        <CardTitle class="line-clamp-2 text-base leading-snug">
          {{ project.title }}
        </CardTitle>
        <div class="flex items-center gap-1">
          <Badge variant="secondary">
            {{ STAGE_TITLES[project.current_stage] ?? project.current_stage }}
          </Badge>
          <Badge :variant="status === 'done' ? 'default' : 'outline'">
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
        v-if="total.count || completedDate"
        class="text-muted-foreground flex items-center justify-between text-xs"
      >
        <span v-if="total.count">选题评分 {{ total.sum }}/{{ total.count * 5 }}</span>
        <span
          v-if="completedDate"
          class="ml-auto"
        >
          完成于 {{ completedDate }}
        </span>
      </CardFooter>
    </Card>
  </RouterLink>
</template>
