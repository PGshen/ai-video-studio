import { describe, expect, it } from 'vitest'
import {
  MAX_FILE_BYTES,
  MAX_FILES,
  MAX_IMAGE_BYTES,
  MAX_IMAGES,
  READ_IMAGE_BYTES,
  READ_TEXT_BYTES,
  classifyFile,
  validateAttachments,
} from './attachmentRules'

const file = (name: string, size: number, type = '') => ({ name, size, type })

describe('classifyFile', () => {
  it('png/jpeg/webp/gif 算图片，其余算文件', () => {
    expect(classifyFile(file('a.png', 10, 'image/png'), 'all').kind).toBe('image')
    expect(classifyFile(file('a.webp', 10, 'image/webp'), 'all').kind).toBe('image')
    expect(classifyFile(file('a.svg', 10, 'image/svg+xml'), 'all').kind).toBe('file')
    expect(classifyFile(file('a.pdf', 10, 'application/pdf'), 'all').kind).toBe('file')
  })

  it('图片超过 5 MB 报错，刚好 5 MB 不报', () => {
    expect(classifyFile(file('a.png', MAX_IMAGE_BYTES, 'image/png'), 'all').error).toBeUndefined()
    expect(classifyFile(file('a.png', MAX_IMAGE_BYTES + 1, 'image/png'), 'all').error).toMatch('图片')
  })

  it('文件超过 20 MB 报错', () => {
    expect(classifyFile(file('a.txt', MAX_FILE_BYTES, 'text/plain'), 'all').error).toBeUndefined()
    expect(classifyFile(file('a.txt', MAX_FILE_BYTES + 1, 'text/plain'), 'all').error).toMatch('文件')
  })

  it('images 模式下非图片报错', () => {
    expect(classifyFile(file('a.pdf', 10, 'application/pdf'), 'images').error).toBe(
      '选题对话只支持图片',
    )
  })

  it('大于 300 kB 的 PDF、大于 2 MB 的其他文件带警告', () => {
    expect(classifyFile(file('a.pdf', READ_IMAGE_BYTES, 'application/pdf'), 'all').warning).toBeUndefined()
    expect(classifyFile(file('a.pdf', READ_IMAGE_BYTES + 1, 'application/pdf'), 'all').warning).toMatch(
      '可能读不到全文',
    )
    expect(classifyFile(file('a.txt', READ_TEXT_BYTES + 1, 'text/plain'), 'all').warning).toMatch(
      '可能读不到全文',
    )
    expect(classifyFile(file('a.png', READ_IMAGE_BYTES + 1, 'image/png'), 'all').warning).toBeUndefined()
  })
})

describe('validateAttachments', () => {
  it('合法时返回 null', () => {
    expect(validateAttachments([file('a.png', 1, 'image/png'), file('b.md', 1)], 'all')).toBeNull()
  })

  it('图片或文件超过数量上限时报错', () => {
    const images = Array.from({ length: MAX_IMAGES + 1 }, (_, i) => file(`${i}.png`, 1, 'image/png'))
    expect(validateAttachments(images, 'all')).toMatch(`${MAX_IMAGES}`)
    const files = Array.from({ length: MAX_FILES + 1 }, (_, i) => file(`${i}.md`, 1))
    expect(validateAttachments(files, 'all')).toMatch(`${MAX_FILES}`)
  })

  it('返回第一个文件级错误', () => {
    expect(validateAttachments([file('a.pdf', 1, 'application/pdf')], 'images')).toBe('选题对话只支持图片')
  })
})
