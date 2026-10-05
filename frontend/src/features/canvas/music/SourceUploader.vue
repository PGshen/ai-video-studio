<script setup lang="ts">
/**
 * 导入音乐的上传区：选择或拖入一首歌，显示进度与错误。客户端先挡扩展名与大小（`checkSourceFile`），
 * 服务端为准（422/409 的中文原因原样显示）。已上传时是"更换歌曲"入口。有一轮在跑时禁用。
 */
import { computed, ref } from 'vue'
import { errorMessage } from '@/api/http'
import { useUploadMusicSourceMutation } from '@/composables/queries'
import type { MusicSourceOut } from '@/types/api'
import { Button } from '@/components/ui/button'
import { SOURCE_EXTENSIONS, checkSourceFile } from './importView'

const props = defineProps<{ projectId: string; busy: boolean; hasSource: boolean }>()
const emit = defineEmits<{ uploaded: [source: MusicSourceOut] }>()

type Phase = 'idle' | 'uploading' | 'done' | 'error' | 'cancelled'

const phase = ref<Phase>('idle')
const percent = ref(0)
const problem = ref<string | null>(null)
const dragging = ref(false)
const input = ref<HTMLInputElement | null>(null)
let controller: AbortController | null = null

const mutation = useUploadMusicSourceMutation(() => props.projectId)
const disabled = computed(() => props.busy || phase.value === 'uploading')
const accept = SOURCE_EXTENSIONS.map((ext) => `.${ext}`).join(',')

async function upload(file: File): Promise<void> {
  if (disabled.value) return
  const rejected = checkSourceFile(file)
  if (rejected !== null) {
    phase.value = 'error'
    problem.value = rejected
    return
  }
  phase.value = 'uploading'
  percent.value = 0
  problem.value = null
  controller = new AbortController()
  try {
    const source = await mutation.mutateAsync({
      file,
      signal: controller.signal,
      onProgress: (loaded, total) => {
        percent.value = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0
      },
    })
    phase.value = 'done'
    emit('uploaded', source)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      phase.value = 'cancelled'
    } else {
      phase.value = 'error'
      problem.value = errorMessage(error)
    }
  } finally {
    controller = null
  }
}

function onPick(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = '' // picking the same file again must fire `change` again
  if (file) void upload(file)
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) void upload(file)
}

function cancel(): void {
  controller?.abort()
}
</script>

<template>
  <div
    class="rounded border border-dashed px-4 py-6 text-center text-sm"
    :class="dragging ? 'bg-primary/5 border-primary' : ''"
    data-testid="music-uploader"
    @dragover.prevent="dragging = !disabled"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
  >
    <p
      v-if="!hasSource"
      class="mb-1 font-medium"
    >
      上传一首歌
    </p>
    <p
      v-else
      class="text-muted-foreground mb-1 text-xs"
      data-testid="music-uploader-replace-hint"
    >
      更换后需要让 agent 重新分析
    </p>
    <p class="text-muted-foreground mb-3 text-xs">
      拖到这里，或选择文件。支持 {{ SOURCE_EXTENSIONS.join(' / ') }}，不超过 150 MB，时长 5–600 秒。
    </p>

    <template v-if="phase === 'uploading'">
      <div
        class="bg-muted mx-auto mb-2 h-2 w-full max-w-sm overflow-hidden rounded"
        role="progressbar"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
        data-testid="music-upload-progress"
      >
        <div
          class="bg-primary h-full"
          :style="{ width: `${percent}%` }"
        />
      </div>
      <p
        class="mb-2 tabular-nums"
        data-testid="music-upload-percent"
      >
        {{ percent >= 100 ? '处理中…（服务端正在校验）' : `上传中 ${percent}%` }}
      </p>
      <Button
        v-if="percent < 100"
        size="sm"
        variant="outline"
        data-testid="music-upload-cancel"
        @click="cancel"
      >
        取消
      </Button>
    </template>
    <template v-else>
      <input
        ref="input"
        type="file"
        class="hidden"
        :accept="accept"
        :disabled="disabled"
        data-testid="music-upload-input"
        @change="onPick"
      >
      <Button
        size="sm"
        :variant="hasSource ? 'outline' : 'default'"
        :disabled="disabled"
        :title="busy ? 'agent 正在运行，等它结束再上传' : undefined"
        data-testid="music-upload-button"
        @click="input?.click()"
      >
        {{ hasSource ? '更换歌曲' : '选择文件' }}
      </Button>
      <p
        v-if="busy"
        class="text-muted-foreground mt-2 text-xs"
        data-testid="music-upload-busy"
      >
        agent 正在运行，等它结束再上传。
      </p>
    </template>

    <p
      v-if="phase === 'error' && problem"
      class="text-destructive mt-2 text-xs"
      role="alert"
      data-testid="music-upload-error"
    >
      {{ problem }}
    </p>
    <p
      v-else-if="phase === 'cancelled'"
      class="text-muted-foreground mt-2 text-xs"
      data-testid="music-upload-cancelled"
    >
      已取消上传。
    </p>
    <p
      v-else-if="phase === 'done'"
      class="mt-2 text-xs"
      data-testid="music-upload-done"
    >
      上传完成。让 agent 调用 analyze_music 分析这首歌。
    </p>
  </div>
</template>
