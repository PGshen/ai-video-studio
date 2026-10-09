<script setup lang="ts">
/**
 * 用户消息下的附件（设计 2026-10-09 §6）：图片显示缩略图，点击在新标签页看原图；文件显示名字和
 * 大小，项目会话里链接到工作区原文件（风格/选题会话没有可访问的工作区，只显示名字）。
 * 真实 turn 的 `attachments` 优先；还没到时用乐观占位的本地预览。
 */
import { computed } from 'vue'
import { FileIcon } from '@lucide/vue'
import { attachmentUrl, workspaceFileUrl } from '@/api/endpoints'
import type { LocalAttachment } from '@/composables/useSessionStream'
import type { AttachmentOut } from '@/types/api'
import { formatBytes } from './attachmentFormat'

const props = defineProps<{
  server?: AttachmentOut[]
  local?: LocalAttachment[]
  projectId: string | null
  sessionId: string | null
}>()

interface Shown {
  kind: 'image' | 'file'
  name: string
  size: number
  src?: string
  href?: string
}

const shown = computed<Shown[]>(() => {
  if (props.server?.length) {
    return props.server.map((a) => {
      const src =
        a.kind === 'image' && a.sha256 && props.sessionId
          ? attachmentUrl(props.sessionId, a.sha256)
          : undefined
      const href =
        a.kind === 'file' && a.path && props.projectId
          ? workspaceFileUrl(props.projectId, a.path)
          : undefined
      return { kind: a.kind, name: a.name, size: a.size, src, href }
    })
  }
  return (props.local ?? []).map((a) => ({ ...a, src: a.previewUrl }))
})
</script>

<template>
  <div
    v-if="shown.length > 0"
    class="flex max-w-full flex-wrap justify-end gap-2"
    data-testid="message-attachments"
  >
    <template
      v-for="(item, index) in shown"
      :key="index"
    >
      <a
        v-if="item.kind === 'image' && item.src"
        :href="item.src"
        target="_blank"
        rel="noopener"
      >
        <img
          :src="item.src"
          :alt="item.name"
          class="size-20 rounded-md border object-cover"
        >
      </a>
      <a
        v-else-if="item.href"
        :href="item.href"
        target="_blank"
        rel="noopener"
        class="bg-muted hover:bg-accent flex items-center gap-2 rounded-md border px-2 py-1 text-xs"
        data-testid="attachment-file"
      >
        <FileIcon class="size-4 shrink-0" />
        <span class="max-w-48 truncate">{{ item.name }}</span>
        <span class="text-muted-foreground">{{ formatBytes(item.size) }}</span>
      </a>
      <span
        v-else
        class="bg-muted flex items-center gap-2 rounded-md border px-2 py-1 text-xs"
      >
        <FileIcon class="size-4 shrink-0" />
        <span class="max-w-48 truncate">{{ item.name }}</span>
        <span class="text-muted-foreground">{{ formatBytes(item.size) }}</span>
      </span>
    </template>
  </div>
</template>
