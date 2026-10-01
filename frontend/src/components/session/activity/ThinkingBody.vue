<script setup lang="ts">
/** 思考行的展开正文：只有文本。OpenAI 的摘要带 markdown 小标题，所以走 Markdown 渲染。 */
import { MessageResponse } from '@/components/ai-elements/message'

defineProps<{ text: string }>()
</script>

<template>
  <MessageResponse
    :content="text"
    class="text-muted-foreground text-sm"
  />
</template>
