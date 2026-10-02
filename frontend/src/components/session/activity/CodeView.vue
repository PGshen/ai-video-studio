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
  <!-- 字号和内边距比通用代码块小一档，适合放进工具面板（`!` 压过组件里写死的 `text-sm`/`p-4`）。 -->
  <div
    class="[&_pre]:p-3! [&_pre]:text-xs! [&_code]:text-xs!"
    data-testid="code-view"
  >
    <CodeBlockContent
      :code="trimmed"
      :language="language as BundledLanguage"
      :show-line-numbers="lineNumbers"
    />
  </div>
</template>
