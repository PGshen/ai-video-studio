import { describe, expect, it } from 'vitest'
import { computeMissingFileAction } from './missingFile'

describe('computeMissingFileAction', () => {
  it('文件没消失时是 none', () => {
    expect(computeMissingFileAction({ fileMissing: false, dirty: false })).toBe('none')
    expect(computeMissingFileAction({ fileMissing: false, dirty: true })).toBe('none')
  })

  it('文件消失且缓冲区干净：close', () => {
    expect(computeMissingFileAction({ fileMissing: true, dirty: false })).toBe('close')
  })

  it('文件消失且缓冲区脏：keep-readonly', () => {
    expect(computeMissingFileAction({ fileMissing: true, dirty: true })).toBe('keep-readonly')
  })
})
