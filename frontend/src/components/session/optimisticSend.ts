/**
 * 发消息 / [继续] 共用的乐观插入流程（M1 最终审查 M3）：先 `add` 插入一条
 * 用户消息占位，再发请求；请求失败（409/网络错误等，turn 从没真正创建）时
 * 用 `remove` 撤回占位——否则它会占着 `useSessionStream` FIFO 队列的队首，
 * 下一条真正发出去的消息的 turn 会被错误配对到这条假消息上。
 */

import type { LocalAttachment } from '@/composables/useSessionStream'

/** 与后端 `api.sessions.CONTINUE_TEXT` 一致：`POST .../continue` 固定发送这条文本。 */
export const CONTINUE_TEXT = '继续'

export interface OptimisticMessages {
  add: (text: string, attachments?: LocalAttachment[]) => string
  remove: (placeholderId: string) => void
}

export async function optimisticSend(
  messages: OptimisticMessages,
  text: string,
  send: () => Promise<unknown>,
  attachments?: LocalAttachment[],
): Promise<void> {
  const placeholderId = messages.add(text, attachments)
  try {
    await send()
  } catch (error) {
    messages.remove(placeholderId)
    throw error
  }
}
