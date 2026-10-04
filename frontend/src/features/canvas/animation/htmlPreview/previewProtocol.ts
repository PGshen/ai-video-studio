/**
 * 父页面与预览 iframe 之间的消息协议（设计 §7.1）。iframe 是不透明源，消息用 `postMessage`；
 * 父页面只信任来自**自己那个 iframe 窗口**的消息，其他窗口发来的一律忽略。
 */
export type PreviewMessage =
  | { type: 'ready'; duration: number }
  | { type: 'error'; message: string }

export function seekMessage(t: number): { type: 'seek'; t: number } {
  return { type: 'seek', t }
}

export function parsePreviewMessage(
  event: { data: unknown; source: unknown },
  frameWindow: unknown,
): PreviewMessage | null {
  if (frameWindow === null || frameWindow === undefined || event.source !== frameWindow) return null
  const data = event.data
  if (typeof data !== 'object' || data === null) return null
  const record = data as Record<string, unknown>
  if (record.type === 'ready' && typeof record.duration === 'number') {
    return { type: 'ready', duration: record.duration }
  }
  if (record.type === 'error' && typeof record.message === 'string') {
    return { type: 'error', message: record.message }
  }
  return null
}
