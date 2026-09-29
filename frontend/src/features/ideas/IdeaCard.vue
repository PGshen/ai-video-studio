<script setup lang="ts">
/**
 * 一张想法卡片（计划 M4 T9）：标题、卖点、反直觉点（突出）、标签、四项评分；按状态给出操作。
 * 只做展示和事件，不直接调接口——页面层处理创建项目/编辑/归档。
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import type { IdeaOut } from '@/types/api'
import { SCORE_DIMENSIONS, ideaTotal, statusLabel } from './ideaView'

const props = defineProps<{ idea: IdeaOut; busy?: boolean }>()
const emit = defineEmits<{
  (e: 'create-project', idea: IdeaOut): void
  (e: 'edit', idea: IdeaOut): void
  (e: 'archive', idea: IdeaOut): void
  (e: 'restore', idea: IdeaOut): void
}>()

const total = computed(() => ideaTotal(props.idea.scores))
</script>

<template>
  <Card
    class="flex flex-col"
    :class="{ 'opacity-60': idea.status === 'archived' }"
    :data-testid="`idea-card-${idea.id}`"
  >
    <CardHeader class="gap-2">
      <div class="flex items-start justify-between gap-2">
        <CardTitle class="text-base leading-snug">
          {{ idea.title }}
        </CardTitle>
        <Badge
          :variant="idea.status === 'picked' ? 'default' : 'outline'"
          class="shrink-0"
        >
          {{ statusLabel(idea.status) }}
        </Badge>
      </div>
      <p
        v-if="idea.pitch"
        class="text-muted-foreground text-sm"
      >
        {{ idea.pitch }}
      </p>
    </CardHeader>

    <CardContent class="flex flex-1 flex-col gap-3">
      <div
        v-if="idea.counterintuitive"
        class="bg-muted rounded-md border-l-4 border-primary px-3 py-2 text-sm"
      >
        <span class="text-muted-foreground text-xs">反直觉点</span>
        <p>{{ idea.counterintuitive }}</p>
      </div>

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

      <div
        v-if="total.count"
        class="grid grid-cols-2 gap-x-4 gap-y-1"
      >
        <div
          v-for="dim in SCORE_DIMENSIONS"
          :key="dim.key"
          class="flex items-center gap-2 text-xs"
        >
          <span class="text-muted-foreground w-12 shrink-0">{{ dim.label }}</span>
          <template v-if="idea.scores[dim.key] !== undefined">
            <div class="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
              <div
                class="bg-primary h-full"
                :style="{ width: `${((idea.scores[dim.key] ?? 0) / 5) * 100}%` }"
              />
            </div>
            <span class="w-3 text-right tabular-nums">{{ idea.scores[dim.key] }}</span>
          </template>
          <span
            v-else
            class="text-muted-foreground"
          >—</span>
        </div>
      </div>
      <p
        v-else
        class="text-muted-foreground text-xs"
      >
        还没有评分
      </p>
    </CardContent>

    <CardFooter class="flex flex-wrap gap-2">
      <template v-if="idea.status === 'idea'">
        <Button
          size="sm"
          :disabled="busy"
          @click="emit('create-project', idea)"
        >
          创建项目
        </Button>
        <Button
          size="sm"
          variant="outline"
          :disabled="busy"
          @click="emit('edit', idea)"
        >
          编辑
        </Button>
        <Button
          size="sm"
          variant="ghost"
          :disabled="busy"
          @click="emit('archive', idea)"
        >
          归档
        </Button>
      </template>
      <template v-else-if="idea.status === 'picked'">
        <Button
          v-if="idea.project_id"
          size="sm"
          variant="outline"
          as-child
        >
          <RouterLink :to="`/projects/${idea.project_id}/topic`">
            打开项目
          </RouterLink>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          :disabled="busy"
          @click="emit('edit', idea)"
        >
          编辑
        </Button>
      </template>
      <template v-else>
        <Button
          size="sm"
          variant="outline"
          :disabled="busy"
          @click="emit('restore', idea)"
        >
          恢复
        </Button>
      </template>
    </CardFooter>
  </Card>
</template>
