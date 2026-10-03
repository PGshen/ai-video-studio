<script setup lang="ts">
/**
 * 一张想法卡片的摘要（列表里用）：标题、卖点（截断）、少量标签、总分，以及「详情」和主操作。
 * 完整内容和其余操作（编辑/归档）在 `IdeaDetailDialog`。只做展示和事件，不直接调接口。
 */
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import type { IdeaOut } from '@/types/api'
import { ideaTotal, statusLabel } from './ideaView'

/** 摘要里最多显示几个标签，其余折叠成「+N」。 */
const VISIBLE_TAGS = 3

const props = defineProps<{ idea: IdeaOut; projectCount: number; busy?: boolean }>()
const emit = defineEmits<{
  (e: 'detail', idea: IdeaOut): void
  (e: 'create-project', idea: IdeaOut): void
  (e: 'open-projects', idea: IdeaOut): void
  (e: 'restore', idea: IdeaOut): void
}>()

const total = computed(() => ideaTotal(props.idea.scores))
const shownTags = computed(() => props.idea.tags.slice(0, VISIBLE_TAGS))
const hiddenTags = computed(() => props.idea.tags.length - shownTags.value.length)
</script>

<template>
  <Card
    class="flex flex-col"
    :class="{ 'opacity-60': idea.status === 'archived' }"
    :data-testid="`idea-card-${idea.id}`"
  >
    <CardHeader class="gap-2">
      <div class="flex items-start justify-between gap-2">
        <CardTitle class="line-clamp-2 text-base leading-snug">
          {{ idea.title }}
        </CardTitle>
        <Badge
          :variant="projectCount > 0 ? 'default' : 'outline'"
          class="shrink-0"
        >
          {{ statusLabel(idea.status, projectCount) }}
        </Badge>
      </div>
      <p
        v-if="idea.pitch"
        class="text-muted-foreground line-clamp-3 text-sm"
      >
        {{ idea.pitch }}
      </p>
    </CardHeader>

    <CardContent class="flex flex-1 flex-wrap content-start items-center gap-1">
      <Badge
        v-for="tag in shownTags"
        :key="tag"
        variant="secondary"
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

    <CardFooter class="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        @click="emit('detail', idea)"
      >
        详情
      </Button>
      <Button
        v-if="idea.status === 'idea'"
        size="sm"
        :disabled="busy"
        @click="emit('create-project', idea)"
      >
        创建项目
      </Button>
      <Button
        v-if="projectCount > 0"
        size="sm"
        variant="ghost"
        @click="emit('open-projects', idea)"
      >
        打开项目
      </Button>
      <Button
        v-else-if="idea.status === 'archived'"
        size="sm"
        variant="ghost"
        :disabled="busy"
        @click="emit('restore', idea)"
      >
        恢复
      </Button>
      <span
        v-if="total.count"
        class="text-muted-foreground ml-auto text-xs tabular-nums"
      >
        评分 {{ total.sum }}/{{ total.count * 5 }}
      </span>
    </CardFooter>
  </Card>
</template>
