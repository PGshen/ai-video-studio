<script setup lang="ts">
/**
 * 一套风格的卡片摘要（风格库列表里用）：名称、分类、简介（截断）、引用/金样本数量，以及「默认」、
 * 「有未保存草稿」和「未保存的新风格」标记。点卡片本身打开详情，右下角的编辑按钮直接进入编辑态。
 */
import { Pencil } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import type { StyleSummaryOut } from '@/types/api'

const props = defineProps<{ item: StyleSummaryOut }>()
const emit = defineEmits<{
  (e: 'open', item: StyleSummaryOut): void
  (e: 'edit', item: StyleSummaryOut): void
}>()
</script>

<template>
  <Card
    class="hover:border-primary flex cursor-pointer flex-col transition-colors"
    :data-testid="`style-card-${props.item.id}`"
    role="button"
    tabindex="0"
    @click="emit('open', props.item)"
    @keydown.enter.self="emit('open', props.item)"
  >
    <CardHeader class="gap-2">
      <div class="flex items-start justify-between gap-2">
        <CardTitle class="line-clamp-2 text-base leading-snug">
          {{ props.item.name }}
        </CardTitle>
        <div class="flex shrink-0 flex-wrap justify-end gap-1">
          <Badge
            v-if="props.item.is_default"
            :data-testid="`style-default-${props.item.id}`"
          >
            默认
          </Badge>
          <Badge variant="outline">
            {{ props.item.category }}
          </Badge>
        </div>
      </div>
      <p
        v-if="props.item.description"
        class="text-muted-foreground line-clamp-3 text-sm"
        :data-testid="`style-description-${props.item.id}`"
      >
        {{ props.item.description }}
      </p>
    </CardHeader>

    <CardContent class="text-muted-foreground flex flex-1 flex-wrap items-center gap-2 text-xs">
      <span>{{ props.item.reference_count }} 个引用 · {{ props.item.exemplar_count }} 个金样本</span>
      <Badge
        v-if="props.item.is_new"
        variant="secondary"
        :data-testid="`style-new-${props.item.id}`"
      >
        未保存的新风格
      </Badge>
      <Badge
        v-else-if="props.item.has_draft"
        variant="secondary"
        :data-testid="`style-draft-${props.item.id}`"
      >
        有未保存草稿
      </Badge>
    </CardContent>

    <!-- 点底部的按钮不应该同时打开详情。 -->
    <CardFooter
      class="flex items-center justify-end"
      @click.stop
    >
      <Button
        size="sm"
        variant="outline"
        :data-testid="`style-edit-${props.item.id}`"
        @click="emit('edit', props.item)"
      >
        <Pencil />
        编辑
      </Button>
    </CardFooter>
  </Card>
</template>
