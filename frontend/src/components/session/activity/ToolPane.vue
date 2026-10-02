<script setup lang="ts">
/**
 * 工具正文的统一外框（设计 §4.3）：标题栏（左：标题/文件名；右：语言、「复制」）+ 限高可滚动
 * 的内容区。复制失败（无剪贴板权限等）时静默，不影响界面。
 */
import { useCopy } from './useCopy'

const props = defineProps<{
  /** 标题栏文字；需要图标/状态点时改用 `title` 插槽。 */
  title?: string
  language?: string
  /** 给了才显示「复制」按钮。 */
  copyText?: string
  tone?: 'default' | 'error'
}>()

const { copied, copy } = useCopy()

function copyAll(): Promise<void> {
  return props.copyText === undefined ? Promise.resolve() : copy(props.copyText)
}
</script>

<template>
  <div
    class="bg-muted/30 overflow-hidden rounded-lg border text-xs"
    :data-testid="tone === 'error' ? 'tool-pane-error' : 'tool-pane'"
  >
    <div class="text-muted-foreground flex items-center justify-between gap-3 border-b px-3 py-1.5">
      <span
        class="flex min-w-0 items-center gap-2 truncate font-mono"
        :class="tone === 'error' ? 'text-destructive' : ''"
        data-testid="tool-pane-title"
      ><slot name="title">{{ title }}</slot></span>
      <span class="flex shrink-0 items-center gap-3">
        <span v-if="language">{{ language }}</span>
        <button
          v-if="copyText !== undefined"
          type="button"
          class="hover:text-foreground"
          data-testid="tool-pane-copy"
          @click="copyAll"
        >{{ copied ? '已复制' : '复制' }}</button>
      </span>
    </div>
    <div
      class="max-h-80 overflow-auto"
      data-testid="tool-pane-body"
    >
      <slot />
    </div>
  </div>
</template>
