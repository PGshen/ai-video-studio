<script setup lang="ts">
/**
 * 工作台左侧竖栏里的一组：组名 + 上方分割线 + 内容。竖栏折叠时组名隐藏，只留分割线。
 * 窄屏（竖栏横排）不显示分割线。
 */
defineProps<{
  title: string
  collapsed?: boolean
}>()
</script>

<template>
  <section
    class="flex min-h-0 flex-col gap-2 border-t pt-3 max-lg:border-t-0 max-lg:pt-0"
    :class="collapsed ? 'lg:items-center' : ''"
    :data-testid="`rail-group-${title}`"
  >
    <h3
      v-if="!collapsed"
      class="text-muted-foreground px-1 text-xs font-medium whitespace-nowrap"
    >
      {{ title }}
    </h3>
    <slot />
  </section>
</template>
