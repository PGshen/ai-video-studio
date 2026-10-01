<script setup lang="ts">
/**
 * 带语法高亮（shiki）和可选行号的代码块内容，复用 ai-elements 的 `CodeBlockContent`。
 * 末尾的那个换行不算一行（文件内容通常以换行结尾，否则会多出一个空的行号）。
 */
import { computed } from 'vue'
import type { BundledLanguage } from 'shiki'
import { CodeBlockContent } from '@/components/ai-elements/code-block'

const props = defineProps<{ code: string; language: string; lineNumbers?: boolean }>()

const trimmed = computed(() => props.code.replace(/\n$/, ''))
</script>

<template>
  <CodeBlockContent
    :code="trimmed"
    :language="language as BundledLanguage"
    :show-line-numbers="lineNumbers"
  />
</template>
