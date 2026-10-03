<script setup lang="ts">
/**
 * 列表底部的翻页条：共 N 项、上一页/下一页、当前页/总页数。只有一页时不显示。
 * `current` 是已收进有效范围的页码（父级的 `page` 可能因为列表变短而越界）。
 */
import { Button } from '@/components/ui/button'

defineProps<{ total: number; totalPages: number; current: number }>()
const page = defineModel<number>('page', { required: true })
</script>

<template>
  <div
    v-if="totalPages > 1"
    class="flex shrink-0 items-center justify-between text-sm"
    data-testid="list-pagination"
  >
    <span class="text-muted-foreground">共 {{ total }} 项</span>
    <div class="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        :disabled="current <= 1"
        @click="page = current - 1"
      >
        上一页
      </Button>
      <span class="tabular-nums">{{ current }} / {{ totalPages }}</span>
      <Button
        size="sm"
        variant="outline"
        :disabled="current >= totalPages"
        @click="page = current + 1"
      >
        下一页
      </Button>
    </div>
  </div>
</template>
