<script setup lang="ts">
/**
 * 项目「信息」的正文（只读）：基本信息、关联选题、风格。放在对话框内容里，对话框打开时才挂载，
 * 所以选题列表和风格文件只在打开时才请求。风格只能展示工作区里的副本（项目没有记录来源预设 id）。
 */
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import {
  useAllIdeasQuery,
  useFileContentQuery,
  useFileTreeQuery,
  useProjectQuery,
} from '@/composables/queries'
import { SCORE_DIMENSIONS } from '@/composables/ideaScores'
import { findProjectIdea, parseStyleHeader, styleFileGroups } from './projectInfo'
import { STAGE_TITLES, stageStatusStyle } from './stageStatus'

const props = defineProps<{ projectId: string }>()

const { data: project } = useProjectQuery(() => props.projectId)
const { data: ideas, isPending: ideasPending } = useAllIdeasQuery()
const { data: tree } = useFileTreeQuery(() => props.projectId)
const { data: styleText } = useFileContentQuery(() => props.projectId, () => 'style/STYLE.md')

const idea = computed(() => findProjectIdea(ideas.value, props.projectId))
const styleHeader = computed(() => parseStyleHeader(styleText.value))
const styleFiles = computed(() => styleFileGroups(tree.value?.files))
const scoreText = computed(() => {
  const scores = idea.value?.scores ?? {}
  return SCORE_DIMENSIONS.filter((dim) => scores[dim.key] !== undefined)
    .map((dim) => `${dim.label} ${scores[dim.key]}`)
    .join(' · ')
})

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div
    class="flex max-h-[60vh] flex-col gap-5 overflow-y-auto pr-1 text-sm"
    data-testid="project-info"
  >
    <section class="flex flex-col gap-2">
      <h4 class="text-muted-foreground text-xs font-medium">
        基本信息
      </h4>
      <dl
        v-if="project"
        class="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1.5"
      >
        <dt class="text-muted-foreground">
          标题
        </dt>
        <dd>{{ project.title }}</dd>
        <dt class="text-muted-foreground">
          当前阶段
        </dt>
        <dd>{{ STAGE_TITLES[project.current_stage] ?? project.current_stage }}</dd>
        <dt class="text-muted-foreground">
          阶段状态
        </dt>
        <dd class="flex flex-wrap gap-x-3 gap-y-1">
          <span
            v-for="stage in project.stages"
            :key="stage.stage"
          >
            {{ STAGE_TITLES[stage.stage] ?? stage.stage }}{{ stageStatusStyle(stage.status).suffix }}
          </span>
        </dd>
        <dt class="text-muted-foreground">
          完成时间
        </dt>
        <dd>{{ project.completed_at ? formatTime(project.completed_at) : '尚未完成' }}</dd>
      </dl>
    </section>

    <section class="flex flex-col gap-2">
      <h4 class="text-muted-foreground text-xs font-medium">
        关联选题
      </h4>
      <p
        v-if="ideasPending"
        class="text-muted-foreground"
      >
        加载中…
      </p>
      <div
        v-else-if="idea"
        class="flex flex-col gap-2"
        data-testid="project-info-idea"
      >
        <p class="font-medium">
          {{ idea.title }}
        </p>
        <p
          v-if="idea.pitch"
          class="text-muted-foreground"
        >
          {{ idea.pitch }}
        </p>
        <p v-if="idea.counterintuitive">
          <span class="text-muted-foreground">反直觉：</span>{{ idea.counterintuitive }}
        </p>
        <div
          v-if="idea.tags.length"
          class="flex flex-wrap gap-1"
        >
          <Badge
            v-for="tag in idea.tags"
            :key="tag"
            variant="secondary"
          >
            {{ tag }}
          </Badge>
        </div>
        <p
          v-if="scoreText"
          class="text-muted-foreground text-xs"
        >
          评分：{{ scoreText }}
        </p>
      </div>
      <p
        v-else
        class="text-muted-foreground"
        data-testid="project-info-no-idea"
      >
        未关联选题（这个项目不是从选题池创建的）
      </p>
    </section>

    <section class="flex flex-col gap-2">
      <h4 class="text-muted-foreground text-xs font-medium">
        风格
      </h4>
      <div data-testid="project-info-style">
        <p class="font-medium">
          {{ styleHeader.name ?? '未命名风格' }}
        </p>
        <p
          v-if="styleHeader.description"
          class="text-muted-foreground"
        >
          {{ styleHeader.description }}
        </p>
        <p
          v-if="styleFiles.references.length"
          class="mt-2"
        >
          <span class="text-muted-foreground">参考：</span>{{ styleFiles.references.join('、') }}
        </p>
        <p v-if="styleFiles.exemplars.length">
          <span class="text-muted-foreground">范例：</span>{{ styleFiles.exemplars.join('、') }}
        </p>
        <p class="text-muted-foreground mt-2 text-xs">
          这是创建项目时复制到工作区的副本，之后在风格库里的修改不会同步过来。
        </p>
      </div>
    </section>
  </div>
</template>
