<script setup lang="ts">
/**
 * 选题池页面（计划 M4）：想法卡片网格。头脑风暴抽屉在 T10 接入。
 */
import IdeaGrid from '@/features/ideas/IdeaGrid.vue'
</script>

<template>
  <div class="flex flex-col gap-4">
    <h1 class="text-lg font-semibold">
      选题池
    </h1>
    <IdeaGrid />
  </div>
</template>
