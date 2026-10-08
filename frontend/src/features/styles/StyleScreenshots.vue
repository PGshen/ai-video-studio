<script setup lang="ts">
/**
 * 编辑态的截图区：缩略图网格（第一张是封面）、上传按钮、拖入文件；每张图可以删除、左移、右移、
 * 设为封面。本组件不碰网络，只发事件；粘贴由上层（`StyleEditView`）监听。
 */
import { ArrowLeft, ArrowRight, ImagePlus, Star, X } from '@lucide/vue'
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { screenshotUrl } from './styleFiles'

const MAX_SCREENSHOTS = 12

const props = defineProps<{
  styleId: string
  names: readonly string[]
  readonly: boolean
  /** 有截图操作（上传、删除、移动）进行中：全部按钮禁用。 */
  uploading: boolean
}>()
const emit = defineEmits<{
  (e: 'upload', files: File[]): void
  (e: 'remove', name: string): void
  (e: 'move', name: string, to: number): void
}>()

const input = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const full = () => props.names.length >= MAX_SCREENSHOTS
const locked = () => props.readonly || props.uploading

function onPick(event: Event): void {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files ?? [])
  if (files.length > 0 && !props.readonly) emit('upload', files)
  target.value = ''
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  if (props.readonly) return
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length > 0) emit('upload', files)
}
</script>

<template>
  <div
    class="flex flex-col gap-2"
    data-testid="shot-dropzone"
    :class="dragging && !readonly ? 'ring-primary rounded-md ring-2' : ''"
    @dragover.prevent="dragging = !readonly"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
  >
    <div class="flex items-center gap-2">
      <span class="text-sm font-medium">截图</span>
      <span class="text-muted-foreground text-xs">
        第一张是封面 · {{ names.length }}/{{ MAX_SCREENSHOTS }}
      </span>
      <Button
        size="sm"
        variant="outline"
        class="ml-auto"
        :disabled="locked() || full()"
        data-testid="shot-add"
        @click="input?.click()"
      >
        <ImagePlus />
        {{ uploading ? '处理中…' : '添加截图' }}
      </Button>
      <input
        ref="input"
        type="file"
        class="hidden"
        accept="image/png,image/jpeg,image/webp"
        multiple
        data-testid="shot-input"
        @change="onPick"
      >
    </div>
    <p
      v-if="full()"
      class="text-muted-foreground text-xs"
    >
      最多 {{ MAX_SCREENSHOTS }} 张，先删除一些再添加。
    </p>
    <p
      v-if="names.length === 0"
      class="text-muted-foreground rounded-md border border-dashed p-3 text-center text-xs"
    >
      还没有截图：点「添加截图」、把图片拖进来，或在这里粘贴（⌘V）。
    </p>
    <div
      v-else
      class="flex gap-2 overflow-x-auto pb-1"
    >
      <div
        v-for="(name, i) in names"
        :key="name"
        class="flex shrink-0 flex-col gap-1"
        :data-testid="`shot-item-${i}`"
      >
        <div class="relative aspect-video h-20 overflow-hidden rounded-md border">
          <img
            :src="screenshotUrl(styleId, name, { draft: true })"
            alt=""
            loading="lazy"
            class="size-full object-cover"
          >
          <span
            v-if="i === 0"
            class="bg-background/80 absolute top-1 left-1 rounded px-1 text-[10px]"
          >
            封面
          </span>
          <Button
            size="icon"
            variant="secondary"
            class="absolute top-1 right-1 size-5"
            aria-label="删除截图"
            :disabled="locked()"
            :data-testid="`shot-remove-${i}`"
            @click="emit('remove', name)"
          >
            <X class="size-3" />
          </Button>
        </div>
        <div class="flex justify-center gap-1">
          <Button
            v-if="i > 0"
            size="icon"
            variant="ghost"
            class="size-6"
            aria-label="左移"
            :disabled="locked()"
            :data-testid="`shot-left-${i}`"
            @click="emit('move', name, i - 1)"
          >
            <ArrowLeft class="size-3.5" />
          </Button>
          <Button
            v-if="i > 0"
            size="icon"
            variant="ghost"
            class="size-6"
            aria-label="设为封面"
            :disabled="locked()"
            :data-testid="`shot-cover-${i}`"
            @click="emit('move', name, 0)"
          >
            <Star class="size-3.5" />
          </Button>
          <Button
            v-if="i < names.length - 1"
            size="icon"
            variant="ghost"
            class="size-6"
            aria-label="右移"
            :disabled="locked()"
            :data-testid="`shot-right-${i}`"
            @click="emit('move', name, i + 1)"
          >
            <ArrowRight class="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
