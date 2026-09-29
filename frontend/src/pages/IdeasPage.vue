<script setup lang="ts">
/**
 * 选题池页面（计划 M4）：想法卡片网格 + 可展开的头脑风暴面板。
 * 面板是页面层的开关，不属于卡片网格；两者都在 `features/ideas/`，由页面组合。
 */
import { ref } from 'vue'
import BrainstormDrawer from '@/features/ideas/BrainstormDrawer.vue'
import IdeaGrid from '@/features/ideas/IdeaGrid.vue'
import { Button } from '@/components/ui/button'

const chatOpen = ref(false)
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">
    <div class="flex items-center justify-between">
      <h1 class="text-lg font-semibold">
        选题池
      </h1>
      <Button
        :variant="chatOpen ? 'secondary' : 'default'"
        size="sm"
        @click="chatOpen = !chatOpen"
      >
        {{ chatOpen ? '收起头脑风暴' : '头脑风暴' }}
      </Button>
    </div>
    <div
      class="grid min-h-0 flex-1 gap-4"
      :class="chatOpen ? 'lg:grid-cols-[minmax(0,1fr)_28rem]' : ''"
    >
      <div class="min-h-0 overflow-y-auto">
        <IdeaGrid />
      </div>
      <BrainstormDrawer
        v-if="chatOpen"
        @close="chatOpen = false"
      />
    </div>
  </div>
</template>
