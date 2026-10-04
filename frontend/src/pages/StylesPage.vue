<script setup lang="ts">
/** 风格库页面：卡片列表（`StyleGrid`）+ 由 URL query 驱动的详情/编辑抽屉（`StyleDrawer`）。 */
import StyleDrawer from '@/features/styles/StyleDrawer.vue'
import StyleGrid from '@/features/styles/StyleGrid.vue'
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <StyleGrid />
    <StyleDrawer />
  </div>
</template>
