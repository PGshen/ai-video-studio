<script setup lang="ts">
/**
 * 截图大图查看（详情态用）：`index` 为 `null` 时关闭；打开时可以用前后按钮切换。
 * 点缩略图的一侧负责设置 `index`，这里只管显示。
 */
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { screenshotUrl } from './styleFiles'

const props = defineProps<{
  styleId: string
  names: readonly string[]
  /** 从未保存的新风格只有草稿，图片地址要取草稿的。 */
  draft?: boolean
}>()
const index = defineModel<number | null>('index', { required: true })

const current = computed(() => (index.value === null ? undefined : props.names[index.value]))

function step(delta: number): void {
  if (index.value === null || props.names.length === 0) return
  index.value = (index.value + delta + props.names.length) % props.names.length
}
</script>

<template>
  <Dialog
    :open="index !== null"
    @update:open="(open) => !open && (index = null)"
  >
    <DialogContent class="flex max-h-[90vh] flex-col gap-3 sm:max-w-4xl">
      <DialogTitle class="sr-only">
        截图预览
      </DialogTitle>
      <DialogDescription class="sr-only">
        第 {{ (index ?? 0) + 1 }} 张，共 {{ names.length }} 张
      </DialogDescription>
      <img
        v-if="current"
        :key="current"
        :src="screenshotUrl(styleId, current, { draft: draft ?? false })"
        alt="风格截图"
        class="min-h-0 w-full flex-1 rounded-md object-contain"
        data-testid="shot-large"
      >
      <div
        v-if="names.length > 1"
        class="flex items-center justify-center gap-3"
      >
        <Button
          size="icon"
          variant="outline"
          aria-label="上一张"
          data-testid="shot-prev"
          @click="step(-1)"
        >
          <ChevronLeft />
        </Button>
        <span class="text-muted-foreground text-sm">
          {{ (index ?? 0) + 1 }} / {{ names.length }}
        </span>
        <Button
          size="icon"
          variant="outline"
          aria-label="下一张"
          data-testid="shot-next"
          @click="step(1)"
        >
          <ChevronRight />
        </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
