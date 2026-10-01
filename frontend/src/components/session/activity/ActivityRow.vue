<script setup lang="ts">
/**
 * 活动组里的一行（设计 §4.3）：折叠态 = 图标 + 类型名 + `·` + 一句摘要 + 状态 + chevron；
 * 展开态在下方显示默认插槽里的正文。展开状态由父组件控制（`open` / `update:open`）。
 */
import type { Component } from 'vue'
import { ChevronRightIcon, LoaderCircleIcon } from '@lucide/vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolStatus } from '@/components/session/toolPresentation'

defineProps<{
  icon: Component
  label: string
  summary?: string
  status: ToolStatus
  open: boolean
}>()
defineEmits<{ (e: 'update:open', open: boolean): void }>()
</script>

<template>
  <Collapsible
    :open="open"
    class="group/row"
    data-testid="activity-row"
    :data-status="status"
    @update:open="$emit('update:open', $event)"
  >
    <CollapsibleTrigger
      class="text-muted-foreground hover:text-foreground flex w-full items-center gap-2 py-2 text-left text-sm"
    >
      <component
        :is="icon"
        class="size-4 shrink-0"
      />
      <span class="shrink-0">{{ label }}</span>
      <template v-if="summary">
        <span class="shrink-0">·</span>
        <span class="text-muted-foreground/80 min-w-0 flex-1 truncate">{{ summary }}</span>
      </template>
      <span
        v-else
        class="flex-1"
      />
      <LoaderCircleIcon
        v-if="status === 'running'"
        class="size-3.5 shrink-0 animate-spin"
      />
      <span
        v-else-if="status === 'error'"
        class="text-destructive shrink-0 text-xs"
      >失败</span>
      <span
        v-else-if="status === 'interrupted'"
        class="shrink-0 text-xs"
      >已中断</span>
      <ChevronRightIcon
        class="size-4 shrink-0 transition-transform group-data-[state=open]/row:rotate-90"
      />
    </CollapsibleTrigger>
    <CollapsibleContent class="pb-2 pl-6">
      <slot />
    </CollapsibleContent>
  </Collapsible>
</template>
