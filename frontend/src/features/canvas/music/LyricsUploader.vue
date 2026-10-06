<script setup lang="ts">
/**
 * 歌词（.lrc）的上传、更换与删除。歌词可选，要先有歌曲才能上传（服务端用歌曲时长校验）。
 * 客户端先挡扩展名与大小（`checkLyricsFile`），服务端为准（422/409 的中文原因原样显示）。
 * 有一轮在跑时禁用。
 */
import { computed, ref } from 'vue'
import { errorMessage } from '@/api/http'
import { useDeleteMusicLyricsMutation, useUploadMusicLyricsMutation } from '@/composables/queries'
import type { MusicLyricsOut } from '@/types/api'
import { Button } from '@/components/ui/button'
import { checkLyricsFile } from './importView'

const props = defineProps<{
  projectId: string
  busy: boolean
  lines: number
  /** 歌词文件存在但不可用（`meta.lyrics_error`）：显示原因并保留删除入口。 */
  broken?: string | null
}>()
const emit = defineEmits<{ uploaded: [lyrics: MusicLyricsOut] }>()

const input = ref<HTMLInputElement | null>(null)
const working = ref(false)
const problem = ref<string | null>(null)
const doneLines = ref<number | null>(null)

const upload = useUploadMusicLyricsMutation(() => props.projectId)
const remove = useDeleteMusicLyricsMutation(() => props.projectId)
const disabled = computed(() => props.busy || working.value)

async function run(task: () => Promise<void>): Promise<void> {
  working.value = true
  problem.value = null
  doneLines.value = null
  try {
    await task()
  } catch (error) {
    problem.value = errorMessage(error)
  } finally {
    working.value = false
  }
}

async function onPick(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = '' // picking the same file again must fire `change` again
  if (!file || disabled.value) return
  const rejected = checkLyricsFile(file)
  if (rejected !== null) {
    problem.value = rejected
    doneLines.value = null
    return
  }
  await run(async () => {
    const result = await upload.mutateAsync({ file })
    doneLines.value = result.lines
    emit('uploaded', result)
  })
}

async function onDelete(): Promise<void> {
  if (disabled.value) return
  await run(async () => {
    await remove.mutateAsync()
  })
}
</script>

<template>
  <div
    class="flex flex-wrap items-center gap-2 rounded border px-3 py-2 text-sm"
    data-testid="lyrics-uploader"
  >
    <span class="font-medium">歌词</span>
    <span
      class="text-muted-foreground text-xs"
      data-testid="lyrics-state"
    >
      {{ broken ? '歌词文件不可用' : lines > 0 ? `已上传 ${lines} 句` : '可选：上传带时间戳的 .lrc，画面会跟着歌词走' }}
    </span>
    <div class="ml-auto flex items-center gap-2">
      <input
        ref="input"
        type="file"
        class="hidden"
        accept=".lrc"
        :disabled="disabled"
        data-testid="lyrics-input"
        @change="onPick"
      >
      <Button
        size="sm"
        variant="outline"
        :disabled="disabled"
        :title="busy ? 'agent 正在运行，等它结束再上传' : undefined"
        data-testid="lyrics-button"
        @click="input?.click()"
      >
        {{ lines > 0 || broken ? '更换歌词' : '上传歌词（可选）' }}
      </Button>
      <Button
        v-if="lines > 0 || broken"
        size="sm"
        variant="ghost"
        :disabled="disabled"
        data-testid="lyrics-delete"
        @click="onDelete"
      >
        删除歌词
      </Button>
    </div>
    <p
      v-if="broken && !problem"
      class="text-destructive basis-full text-xs"
      role="alert"
      data-testid="lyrics-broken"
    >
      {{ broken }}。可以重新上传，或删除歌词。
    </p>
    <p
      v-if="problem"
      class="text-destructive basis-full text-xs"
      role="alert"
      data-testid="lyrics-error"
    >
      {{ problem }}
    </p>
    <p
      v-else-if="doneLines !== null"
      class="basis-full text-xs"
      data-testid="lyrics-done"
    >
      歌词已上传（{{ doneLines }} 句）。让 agent 重新读歌词（简报里需要写「歌词意象」）。
    </p>
  </div>
</template>
