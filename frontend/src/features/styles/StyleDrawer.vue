<script setup lang="ts">
/**
 * 风格抽屉（计划 style-library T7）：右侧滑出，状态完全由 URL query 驱动——`?style=<id>&mode=view|edit`
 * （缺省或未知的 mode 按 view）。刷新页面、从卡片的编辑按钮进入都能回到同一状态。详情态和编辑态
 * 切换用 `router.replace`，不污染历史；关闭只清掉 `style` 和 `mode`，保留别的参数。关闭抽屉不丢草稿。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import StyleDetailView from './StyleDetailView.vue'
import StyleEditView from './StyleEditView.vue'

const route = useRoute()
const router = useRouter()

const styleId = computed(() => {
  const value = route.query.style
  return typeof value === 'string' && value !== '' ? value : null
})
const mode = computed<'view' | 'edit'>(() => (route.query.mode === 'edit' ? 'edit' : 'view'))

// 关闭时 URL 立刻清掉，但抽屉还要滑出约 300ms：这段时间继续显示最后一次的内容，免得变成空白。
const shown = ref<{ id: string; mode: 'view' | 'edit' } | null>(null)
watch(
  [styleId, mode],
  ([id, currentMode]) => {
    if (id !== null) shown.value = { id, mode: currentMode }
  },
  { immediate: true },
)

function go(id: string, nextMode: 'view' | 'edit'): void {
  void router.replace({ query: { ...route.query, style: id, mode: nextMode } })
}

function close(): void {
  const rest = { ...route.query }
  delete rest.style
  delete rest.mode
  void router.replace({ query: rest })
}

function onOpenChange(open: boolean): void {
  if (!open) close()
}

function onDiscarded(wasNew: boolean): void {
  if (wasNew || shown.value === null) close()
  else go(shown.value.id, 'view')
}
</script>

<template>
  <Sheet
    :open="styleId !== null"
    @update:open="onOpenChange"
  >
    <SheetContent
      class="w-[min(96vw,1400px)] gap-3 p-6 sm:max-w-none"
      @open-auto-focus.prevent
    >
      <SheetHeader class="p-0">
        <SheetTitle>{{ shown?.mode === 'edit' ? '编辑风格' : '风格详情' }}</SheetTitle>
        <SheetDescription class="sr-only">
          风格库里的一套风格
        </SheetDescription>
      </SheetHeader>
      <template v-if="shown !== null">
        <StyleEditView
          v-if="shown.mode === 'edit'"
          :key="`edit-${shown.id}`"
          :style-id="shown.id"
          @saved="go(shown.id, 'view')"
          @discarded="onDiscarded"
          @close="close"
        />
        <StyleDetailView
          v-else
          :key="`view-${shown.id}`"
          :style-id="shown.id"
          @edit="go(shown.id, 'edit')"
          @open="go($event, 'view')"
          @close="close"
        />
      </template>
    </SheetContent>
  </Sheet>
</template>
