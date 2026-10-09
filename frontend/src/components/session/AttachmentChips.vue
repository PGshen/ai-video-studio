<script setup lang="ts">
/**
 * 输入框上方待发送的附件（设计 2026-10-09 §6）：图片显示缩略图，文件显示图标、名字和大小；
 * 超限或读不全的给出提示，可以逐个移除。必须放在 `PromptInput` 里面（用它的上下文）。
 */
import { computed } from 'vue'
import { FileIcon, XIcon } from '@lucide/vue'
import { PromptInputHeader, usePromptInput } from '@/components/ai-elements/prompt-input'
import { type AttachmentAccept, classifyFile } from './attachmentRules'
import { formatBytes } from './attachmentFormat'

const props = defineProps<{ accept: AttachmentAccept }>()

const { files, removeFile } = usePromptInput()

const chips = computed(() =>
  files.value.map((item) => {
    const raw = item.file
    const verdict = raw
      ? classifyFile(raw, props.accept)
      : { kind: 'file' as const, error: undefined, warning: undefined }
    return {
      id: item.id,
      name: item.filename ?? raw?.name ?? '附件',
      size: raw?.size ?? 0,
      url: item.url,
      ...verdict,
    }
  }),
)
</script>

<template>
  <PromptInputHeader v-if="chips.length > 0">
    <div
      v-for="chip in chips"
      :key="chip.id"
      class="bg-muted flex max-w-64 items-center gap-2 rounded-md border px-2 py-1 text-xs"
      :class="chip.error ? 'border-destructive' : ''"
    >
      <img
        v-if="chip.kind === 'image'"
        :src="chip.url"
        :alt="chip.name"
        class="size-8 shrink-0 rounded object-cover"
      >
      <FileIcon
        v-else
        class="text-muted-foreground size-4 shrink-0"
      />
      <div class="min-w-0">
        <div class="truncate font-medium">
          {{ chip.name }}
        </div>
        <div class="text-muted-foreground">
          {{ formatBytes(chip.size) }}
        </div>
        <div
          v-if="chip.error"
          class="text-destructive"
        >
          {{ chip.error }}
        </div>
        <div
          v-else-if="chip.warning"
          class="text-amber-600 dark:text-amber-400"
        >
          {{ chip.warning }}
        </div>
      </div>
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground shrink-0"
        :aria-label="`移除 ${chip.name}`"
        @click="removeFile(chip.id)"
      >
        <XIcon class="size-3.5" />
      </button>
    </div>
  </PromptInputHeader>
</template>
