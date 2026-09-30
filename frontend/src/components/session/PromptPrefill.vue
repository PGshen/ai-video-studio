<script setup lang="ts">
/**
 * 往 `PromptInput` 的输入框里预填文本（计划 M5 T13）。必须放在 `<PromptInput>` 里面（用它提供的
 * 输入上下文）。`prefill.key` 变化时才写入，同一个 key 只写一次，不会覆盖使用者之后的编辑。
 */
import { watch } from 'vue'
import { usePromptInput } from '@/components/ai-elements/prompt-input/context'

const props = defineProps<{ prefill: { text: string; key: string } | null | undefined }>()

const { setTextInput } = usePromptInput()

watch(
  () => props.prefill?.key,
  (key) => {
    if (key && props.prefill) setTextInput(props.prefill.text)
  },
  { immediate: true },
)
</script>

<template>
  <span class="hidden" />
</template>
