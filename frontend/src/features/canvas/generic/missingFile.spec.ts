import { describe, expect, it } from 'vitest'
import { computeMissingFileAction } from './missingFile'

describe('computeMissingFileAction', () => {
  it('文件还在文件树里：不做任何事', () => {
    expect(computeMissingFileAction({ fileMissing: false, dirty: false })).toBe('none')
    expect(computeMissingFileAction({ fileMissing: false, dirty: true })).toBe('none')
  })

  it('文件消失、缓冲区干净：关闭编辑器', () => {
    expect(computeMissingFileAction({ fileMissing: true, dirty: false })).toBe('close')
  })

  it('文件消失、缓冲区脏：保留内容只读展示，不自动关闭/重建', () => {
    expect(computeMissingFileAction({ fileMissing: true, dirty: true })).toBe('keep-readonly')
  })
})
