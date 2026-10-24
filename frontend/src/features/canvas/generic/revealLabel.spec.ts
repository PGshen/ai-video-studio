import { describe, expect, it } from 'vitest'
import { revealLabel } from './revealLabel'

describe('revealLabel', () => {
  it('按平台给出「在文件管理器中打开」的按钮文字', () => {
    expect(revealLabel('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe('在 Finder 中打开')
    expect(revealLabel('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('在文件夹中打开')
    expect(revealLabel('Mozilla/5.0 (X11; Linux x86_64)')).toBe('在文件管理器中打开')
  })
})
