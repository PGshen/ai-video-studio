import { ref } from 'vue'

/** 复制到剪贴板；成功后 `copied` 短暂为真。剪贴板不可用（无权限等）时静默，不影响界面。 */
export function useCopy(resetMs = 1500) {
  const copied = ref(false)
  async function copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text)
      copied.value = true
      setTimeout(() => {
        copied.value = false
      }, resetMs)
    } catch {
      /* clipboard unavailable */
    }
  }
  return { copied, copy }
}
