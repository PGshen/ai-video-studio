<script setup lang="ts">
/**
 * 「试听」按钮（计划 M5 T12）：真实调用 TTS，可能产生费用，所以旁边固定写明；请求进行中禁用，
 * 失败时在按钮下面显示后端的中文原因（缺 key、供应商出错等）。语速不合法时禁用。
 */
import { Button } from '@/components/ui/button'
import { useVoicePreview } from '@/composables/useVoicePreview'

const props = defineProps<{
  voice: string
  /** 已解析好的语速；`null` 表示输入不合法，按钮禁用。 */
  speed: number | null
}>()

const { loading, playing, error, play, stop } = useVoicePreview()

function click(): void {
  if (playing.value) {
    stop()
    return
  }
  if (props.speed !== null) void play(props.voice, props.speed)
}
</script>

<template>
  <div class="flex flex-col items-start gap-1">
    <Button
      variant="outline"
      size="sm"
      :disabled="loading || speed === null"
      title="试听会调用 TTS，可能产生费用"
      @click="click"
    >
      {{ loading ? '合成中…' : playing ? '停止' : '试听' }}
    </Button>
    <p
      v-if="error"
      class="text-destructive max-w-56 text-xs"
    >
      {{ error }}
    </p>
  </div>
</template>
