<script setup lang="ts">
/**
 * 想法卡片的详情对话框：完整标题、卖点、反直觉点、标签、四项评分，以及按状态给出的操作。
 * 只做展示和事件——卡片网格里的列表项只留摘要，其余内容都在这里看。
 */
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { IdeaOut } from '@/types/api'
import { SCORE_DIMENSIONS, ideaTotal, statusLabel } from './ideaView'

defineProps<{ idea: IdeaOut | null; projectCount: number; busy?: boolean }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{
  (e: 'create-project', idea: IdeaOut): void
  (e: 'open-projects', idea: IdeaOut): void
  (e: 'edit', idea: IdeaOut): void
  (e: 'archive', idea: IdeaOut): void
  (e: 'restore', idea: IdeaOut): void
}>()
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent
      v-if="idea"
      class="max-h-[90vh] overflow-y-auto"
      data-testid="idea-detail"
    >
      <DialogHeader>
        <div class="flex items-start gap-2 pr-6">
          <DialogTitle class="leading-snug">
            {{ idea.title }}
          </DialogTitle>
          <Badge
            :variant="projectCount > 0 ? 'default' : 'outline'"
            class="shrink-0"
          >
            {{ statusLabel(idea.status, projectCount) }}
          </Badge>
        </div>
        <DialogDescription v-if="idea.pitch">
          {{ idea.pitch }}
        </DialogDescription>
        <DialogDescription
          v-else
          class="sr-only"
        >
          想法卡片详情
        </DialogDescription>
      </DialogHeader>

      <div class="flex flex-col gap-4">
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
          v-if="ideaTotal(idea.scores).count"
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
      </div>

      <DialogFooter class="gap-2 sm:justify-start">
        <template v-if="idea.status === 'idea'">
          <Button
            size="sm"
            :disabled="busy"
            @click="emit('create-project', idea)"
          >
            创建项目
          </Button>
          <Button
            v-if="projectCount > 0"
            size="sm"
            variant="outline"
            @click="emit('open-projects', idea)"
          >
            打开项目
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
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
