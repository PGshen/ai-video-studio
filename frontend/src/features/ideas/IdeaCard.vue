<script setup lang="ts">
/**
 * 一张想法卡片的摘要（列表里用）：标题、卖点（截断）、少量标签、总分和主操作；点卡片本身打开详情。
 * 完整内容和其余操作（编辑/归档）在 `IdeaDetailDialog`。删除按钮自带确认框，直接调删除接口。
 */
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import ConfirmDeleteButton from '@/components/ConfirmDeleteButton.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { useDeleteIdeaMutation } from '@/composables/queries'
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

const deleteMutation = useDeleteIdeaMutation()

const total = computed(() => ideaTotal(props.idea.scores))
const shownTags = computed(() => props.idea.tags.slice(0, VISIBLE_TAGS))
const hiddenTags = computed(() => props.idea.tags.length - shownTags.value.length)
</script>

<template>
  <Card
    class="hover:border-primary flex cursor-pointer flex-col transition-colors"
    :class="{ 'opacity-60': idea.status === 'archived' }"
    :data-testid="`idea-card-${idea.id}`"
    role="button"
    tabindex="0"
    @click="emit('detail', idea)"
    @keydown.enter.self="emit('detail', idea)"
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

    <!-- 点底部的按钮不应该同时打开详情。 -->
    <CardFooter
      class="flex items-center gap-2"
      @click.stop
    >
      <Button
        v-if="idea.status === 'idea'"
        size="sm"
        variant="outline"
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
        关联项目
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
      <ConfirmDeleteButton
        :test-id="`idea-delete-${idea.id}`"
        :title="`删除选题「${idea.title}」？`"
        :description="
          projectCount > 0
            ? `这张卡片已创建 ${projectCount} 个项目，需要先删除这些项目才能删除卡片。`
            : '删除后不能恢复。想以后还能找回，请用归档。'
        "
        :action="() => deleteMutation.mutateAsync(idea.id)"
      />
      <span
        v-if="total.count"
        class="text-muted-foreground ml-auto text-xs tabular-nums"
      >
        评分 {{ total.sum }}/{{ total.count * 5 }}
      </span>
    </CardFooter>
  </Card>
</template>
