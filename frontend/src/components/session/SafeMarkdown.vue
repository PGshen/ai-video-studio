<script setup lang="ts">
/**
 * 渲染不可信的模型输出（助手回复、思考）：源文本里的原始 HTML 先转义（`markdownSafe`），
 * 渲染时再拦截危险标签（`blockedHtml`），并关掉链接 favicon（外联请求）。样式类通过属性透传给 Markdown 根节点。
 */
import { computed } from 'vue'
import { MessageResponse } from '@/components/ai-elements/message'
import { BLOCKED_COMPONENTS } from './blockedHtml'
import { escapeRawHtml } from './markdownSafe'

/** 默认会给链接加载 `<域名>/favicon.ico`：模型一提到某个域名浏览器就去请求它，被提示注入时数据可以编码进域名外泄。 */
const LINK_OPTIONS = { favicon: false }

const props = defineProps<{ content: string }>()
const safe = computed(() => escapeRawHtml(props.content))
</script>

<template>
  <MessageResponse
    :content="safe"
    :components="BLOCKED_COMPONENTS"
    :link-options="LINK_OPTIONS"
  />
</template>
