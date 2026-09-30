<script setup lang="ts">
/**
 * 选题池页面（计划 M4）：想法卡片网格 + 可展开的头脑风暴面板。
 * 面板是页面层的开关，不属于卡片网格；两者都在 `features/ideas/`，由页面组合。
 */
import { ref, watch } from 'vue'
import BrainstormDrawer from '@/features/ideas/BrainstormDrawer.vue'
import IdeaGrid from '@/features/ideas/IdeaGrid.vue'
import { Button } from '@/components/ui/button'

const chatOpen = ref(false)
// 第一次打开后保持挂载（TD-40）：收起只是隐藏，SSE 不断开，agent 在后台建的卡片仍实时出现在网格里。
// 从没打开过时不挂载，免得页面一加载就去请求会话列表。
const chatMounted = ref(false)
watch(chatOpen, (open) => {
  if (open) chatMounted.value = true
})
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
        v-if="chatMounted"
        v-show="chatOpen"
        @close="chatOpen = false"
      />
    </div>
  </div>
</template>
