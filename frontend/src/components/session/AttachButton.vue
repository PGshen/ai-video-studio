<script setup lang="ts">
/** 输入框里的回形针按钮：打开 `PromptInput` 的文件选择框。 */
import { PaperclipIcon } from '@lucide/vue'
import { PromptInputButton, usePromptInput } from '@/components/ai-elements/prompt-input'

defineProps<{ disabled?: boolean; label: string }>()

const { openFileDialog } = usePromptInput()
</script>

<template>
  <PromptInputButton
    type="button"
    :disabled="disabled"
    :aria-label="label"
    :title="label"
    @click="openFileDialog"
  >
    <PaperclipIcon class="size-4" />
  </PromptInputButton>
</template>
