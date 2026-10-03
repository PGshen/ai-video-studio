/**
 * 叙事画布的"整体播放"：按镜头顺序连续播放各镜头的配音，再次触发则暂停。
 * 用一个脱离文档的 `Audio` 元素依次切换 `src`；镜头详情里的 `BeatTimeline`
 * 有自己的 `<audio>`，两者互不影响。
 *
 * 状态：`currentId` 是当前（或暂停所在）镜头，空闲时为 `null`；
 * 暂停后再触发从暂停处继续（或从新选中的镜头开始），一轮播完回到空闲。
 */
import { getCurrentScope, onScopeDispose, ref, watch } from 'vue'

export interface PlaylistItem {
  id: string
  url: string
}

export function useScenePlayback(items: () => PlaylistItem[]) {
  const currentId = ref<string | null>(null)
  const isPlaying = ref(false)
  let audio: HTMLAudioElement | null = null

  function stop(): void {
    audio?.pause()
    isPlaying.value = false
    currentId.value = null
  }

  async function playItem(item: PlaylistItem, load: boolean): Promise<void> {
    const el = ensureAudio()
    currentId.value = item.id
    if (load) el.src = item.url
    isPlaying.value = true
    try {
      await el.play()
    } catch {
      // 浏览器拒绝播放（没有用户手势、音频不可用）：回到暂停态，不留在"播放中"。
      isPlaying.value = false
    }
  }

  function onEnded(): void {
    const list = items()
    const next = list[list.findIndex((i) => i.id === currentId.value) + 1]
    if (next === undefined) stop()
    else void playItem(next, true)
  }

  function ensureAudio(): HTMLAudioElement {
    if (audio === null) {
      audio = new Audio()
      audio.addEventListener('ended', onEnded)
      audio.addEventListener('error', stop)
    }
    return audio
  }

  /**
   * 播放/暂停。空闲或暂停时从 `startId`（通常是用户选中的镜头）开始往后播：
   * 它就是暂停所在的镜头则从暂停处继续，否则重新加载；`startId` 不在列表里
   * 时退回暂停所在的镜头，再退回第一个。
   */
  function toggle(startId?: string | null): void {
    if (isPlaying.value) {
      audio?.pause()
      isPlaying.value = false
      return
    }
    const list = items()
    const target =
      list.find((i) => i.id === startId) ?? list.find((i) => i.id === currentId.value) ?? list[0]
    if (target !== undefined) void playItem(target, target.id !== currentId.value)
  }

  /** 播放中用户点了另一个镜头：从那个镜头开始往后播；没在播放时什么也不做。 */
  function jumpTo(id: string): void {
    if (!isPlaying.value || id === currentId.value) return
    const target = items().find((i) => i.id === id)
    if (target !== undefined) void playItem(target, true)
  }

  // 当前镜头从列表里消失（回滚/删除）：停止，避免继续播一个已经不存在的镜头。
  watch(
    () => items().map((i) => i.id),
    (ids) => {
      if (currentId.value !== null && !ids.includes(currentId.value)) stop()
    },
  )

  if (getCurrentScope()) {
    onScopeDispose(() => {
      audio?.pause()
      audio?.removeEventListener('ended', onEnded)
      audio?.removeEventListener('error', stop)
    })
  }

  return { currentId, isPlaying, toggle, jumpTo }
}
