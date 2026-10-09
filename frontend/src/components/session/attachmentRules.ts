/**
 * 对话附件的前端预校验（设计 2026-10-09 §4.1、§6、修订 R2）。数值与后端
 * `api/attachments.py`、`agent/claude_scope.MAX_READ_IMAGE_BYTES`、`agent/fallback_tools.MAX_READ_BYTES`
 * 一致；最终以后端校验为准，这里只为了及时提示。
 */

export type AttachmentAccept = 'all' | 'images'

export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const MAX_IMAGES = 6
export const MAX_FILE_BYTES = 20 * 1024 * 1024
export const MAX_FILES = 10
/** Claude 的 Read 能打开的图片/PDF 上限。 */
export const READ_IMAGE_BYTES = 300_000
/** OpenAI 运行时 `read_file` 的上限。 */
export const READ_TEXT_BYTES = 2_000_000

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']

const UNREADABLE_WARNING = 'agent 可能读不到全文，建议转成文本后再上传'

export interface FileLike {
  name: string
  size: number
  type: string
}

export interface FileVerdict {
  kind: 'image' | 'file'
  error?: string
  warning?: string
}

function megabytes(bytes: number): number {
  return bytes / (1024 * 1024)
}

export function classifyFile(file: FileLike, accept: AttachmentAccept): FileVerdict {
  if (IMAGE_TYPES.includes(file.type)) {
    if (file.size > MAX_IMAGE_BYTES)
      return { kind: 'image', error: `图片 ${file.name} 超过 ${megabytes(MAX_IMAGE_BYTES)} MB 上限` }
    return { kind: 'image' }
  }
  if (accept === 'images') return { kind: 'file', error: '选题对话只支持图片' }
  if (file.size > MAX_FILE_BYTES)
    return { kind: 'file', error: `文件 ${file.name} 超过 ${megabytes(MAX_FILE_BYTES)} MB 上限` }
  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  const limit = isPdf ? READ_IMAGE_BYTES : READ_TEXT_BYTES
  return file.size > limit ? { kind: 'file', warning: UNREADABLE_WARNING } : { kind: 'file' }
}

/** 整组附件的第一个问题（数量或单个文件），没有问题返回 `null`。 */
export function validateAttachments(files: FileLike[], accept: AttachmentAccept): string | null {
  const verdicts = files.map((file) => classifyFile(file, accept))
  const firstError = verdicts.find((verdict) => verdict.error)?.error
  if (firstError) return firstError
  if (verdicts.filter((v) => v.kind === 'image').length > MAX_IMAGES)
    return `每条消息最多 ${MAX_IMAGES} 张图片`
  if (verdicts.filter((v) => v.kind === 'file').length > MAX_FILES)
    return `每条消息最多 ${MAX_FILES} 个文件`
  return null
}

/** `<input type="file" accept>` 的值：images 模式只列图片类型，否则不限制。 */
export function acceptAttribute(accept: AttachmentAccept): string | undefined {
  return accept === 'images' ? IMAGE_TYPES.join(',') : undefined
}
