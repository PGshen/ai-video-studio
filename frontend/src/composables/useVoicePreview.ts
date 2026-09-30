/**
 * 音色试听（计划 M5 T12）：调 `POST /api/tts/preview`（真实合成，可能产生费用；后端按音色+语速
 * 缓存，同一组合只合成一次），把返回的 mp3 用 `<audio>` 播放。语音设置页和项目设置对话框共用
 * （所以放在 `composables/`，`features/*` 之间不能互相 import）。
 */

import { onBeforeUnmount, ref } from 'vue'
import { previewVoice } from '@/api/endpoints'
import { errorMessage } from '@/api/http'

export function useVoicePreview() {
  const loading = ref(false)
  const playing = ref(false)
  const error = ref<string | null>(null)
  let audio: HTMLAudioElement | null = null
  let objectUrl: string | null = null

  function stop(): void {
    audio?.pause()
    audio = null
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    objectUrl = null
    playing.value = false
  }

  async function play(voice: string, speed: number): Promise<void> {
    stop()
    error.value = null
    loading.value = true
    try {
      const blob = await previewVoice(voice, speed)
      objectUrl = URL.createObjectURL(blob)
      audio = new Audio(objectUrl)
      audio.addEventListener('ended', stop)
      playing.value = true
      await audio.play()
    } catch (err) {
      stop()
      error.value = errorMessage(err)
    } finally {
      loading.value = false
    }
  }

  onBeforeUnmount(stop)
  return { loading, playing, error, play, stop }
}
