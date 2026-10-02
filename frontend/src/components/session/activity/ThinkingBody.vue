<script setup lang="ts">
/**
 * 思考行的展开正文：只有文本。OpenAI 的摘要带 markdown 小标题，所以走 Markdown 渲染。
 * Markdown 根节点自带前景色，会盖掉外面传进去的 `text-muted-foreground`，所以让根节点
 * 继承外层 wrapper 的颜色。
 */
import SafeMarkdown from '@/components/session/SafeMarkdown.vue'

defineProps<{ text: string }>()
</script>

<template>
  <div class="text-muted-foreground text-sm">
    <SafeMarkdown
      :content="text"
      class="text-inherit!"
    />
  </div>
</template>
