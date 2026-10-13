<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { InputGroupTextarea } from '@/components/ui/input-group'
import { cn } from '@/lib/utils'
import { computed, ref } from 'vue'
import { usePromptInput } from './context'

type PromptInputTextareaProps = InstanceType<typeof InputGroupTextarea>['$props']

interface Props extends /* @vue-ignore */ PromptInputTextareaProps {
  class?: HTMLAttributes['class']
}

const props = defineProps<Props>()

const { textInput, setTextInput, addFiles } = usePromptInput()
const isComposing = ref(false)

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    if (isComposing.value || e.isComposing || e.shiftKey)
      return

    e.preventDefault()

    const textarea = e.currentTarget as HTMLTextAreaElement | null
    const submitButton = textarea?.form?.querySelector('button[type="submit"]') as HTMLButtonElement | null

    if (submitButton?.disabled)
      return

    textarea?.form?.requestSubmit()
  }
  // Backspace never removes attachments; they are removed only via their chip's remove button.
}

function handlePaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items)
    return

  const pastedFiles: File[] = []
  for (const item of Array.from(items)) {
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file)
        pastedFiles.push(file)
    }
  }

  if (pastedFiles.length > 0) {
    e.preventDefault()
    addFiles(pastedFiles)
  }
}

const modelValue = computed({
  get: () => textInput.value,
  set: val => setTextInput(val),
})
</script>

<template>
  <InputGroupTextarea
    v-model="modelValue"
    placeholder="What would you like to know?"
    name="message"
    :class="cn('field-sizing-content max-h-48 min-h-16', props.class)"
    v-bind="props"
    @keydown="handleKeyDown"
    @paste="handlePaste"
    @compositionstart="isComposing = true"
    @compositionend="isComposing = false"
  />
</template>
