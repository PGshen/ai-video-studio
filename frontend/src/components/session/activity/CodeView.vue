<script setup lang="ts">
/** 带语法高亮（shiki）和可选行号的代码块内容，复用 ai-elements 的 `CodeBlockContent`。 */
import type { BundledLanguage } from 'shiki'
import { CodeBlockContent } from '@/components/ai-elements/code-block'

defineProps<{ code: string; language: string; lineNumbers?: boolean }>()
</script>

<template>
  <CodeBlockContent
    :code="code"
    :language="language as BundledLanguage"
    :show-line-numbers="lineNumbers"
  />
</template>
