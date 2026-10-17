import { describe, expect, it } from 'vitest'
import { fileManagerName } from './fileManagerName'

describe('fileManagerName', () => {
  it('按平台给出文件管理器名字', () => {
    expect(fileManagerName('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe('Finder')
    expect(fileManagerName('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('资源管理器')
    expect(fileManagerName('Mozilla/5.0 (X11; Linux x86_64)')).toBe('文件管理器')
  })
})
