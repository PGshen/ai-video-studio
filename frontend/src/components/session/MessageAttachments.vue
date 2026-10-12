<script setup lang="ts">
/**
 * 用户消息下的附件（设计 2026-10-09 §6）：图片显示缩略图，点击在本页弹窗看原图（多张时可左右切换）；文件显示名字和
 * 大小，项目会话里链接到工作区原文件（风格/选题会话没有可访问的工作区，只显示名字）。文件只下载、
 * 不在应用源上直接打开：上传的 .html/.svg 里的脚本否则会以应用身份运行。
 * 真实 turn 的 `attachments` 优先；还没到时用乐观占位的本地预览。
 */
import { computed, ref } from 'vue'
import { ChevronLeft, ChevronRight, FileIcon } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
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

/** Images that can be viewed full size; the dialog steps through these. */
const images = computed(() => shown.value.filter((item) => item.kind === 'image' && item.src))
const viewingIndex = ref<number | null>(null)
const viewing = computed(() =>
  viewingIndex.value === null ? undefined : images.value[viewingIndex.value],
)

function open(item: Shown): void {
  viewingIndex.value = images.value.indexOf(item)
}

function step(delta: number): void {
  const count = images.value.length
  if (viewingIndex.value === null || count === 0) return
  viewingIndex.value = (viewingIndex.value + delta + count) % count
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
}
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
      <button
        v-if="item.kind === 'image' && item.src"
        type="button"
        class="cursor-zoom-in"
        :aria-label="`查看图片 ${item.name}`"
        data-testid="attachment-image"
        @click="open(item)"
      >
        <img
          :src="item.src"
          :alt="item.name"
          class="size-20 rounded-md border object-cover"
        >
      </button>
      <a
        v-else-if="item.href"
        :href="item.href"
        :download="item.name"
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
    <Dialog
      :open="viewing !== undefined"
      @update:open="(isOpen) => !isOpen && (viewingIndex = null)"
    >
      <DialogContent
        class="sm:max-w-4xl"
        @keydown="onKeydown"
      >
        <DialogTitle class="truncate pr-6 text-sm font-normal">
          {{ viewing?.name }}
        </DialogTitle>
        <DialogDescription class="sr-only">
          图片附件原图
        </DialogDescription>
        <img
          v-if="viewing"
          :key="viewing.src"
          :src="viewing.src"
          :alt="viewing.name"
          class="max-h-[75vh] w-full rounded-md object-contain"
          data-testid="attachment-image-large"
        >
        <div
          v-if="images.length > 1"
          class="flex items-center justify-center gap-3"
        >
          <Button
            size="icon"
            variant="outline"
            aria-label="上一张"
            data-testid="attachment-image-prev"
            @click="step(-1)"
          >
            <ChevronLeft />
          </Button>
          <span
            class="text-muted-foreground text-sm"
            data-testid="attachment-image-counter"
          >
            {{ (viewingIndex ?? 0) + 1 }} / {{ images.length }}
          </span>
          <Button
            size="icon"
            variant="outline"
            aria-label="下一张"
            data-testid="attachment-image-next"
            @click="step(1)"
          >
            <ChevronRight />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
