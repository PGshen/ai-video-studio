import { describe, expect, it } from 'vitest'
import type { SceneCheckOut } from '@/types/api'
import { checkLabel, checkTone } from './checkSummary'

const base: SceneCheckOut = { status: 'passed', stale: false, checked_at: null, images: [] }

describe('checkTone', () => {
  it('没检查过（或还没拉到数据）是 none', () => {
    expect(checkTone(null)).toBe('none')
    expect(checkTone({ ...base, status: 'not_checked' })).toBe('none')
  })

  it('通过 / 失败按状态区分', () => {
    expect(checkTone(base)).toBe('passed')
    expect(checkTone({ ...base, status: 'failed' })).toBe('failed')
  })

  it('已过期优先于通过，失败仍然是失败', () => {
    expect(checkTone({ ...base, stale: true })).toBe('stale')
    expect(checkTone({ ...base, status: 'failed', stale: true })).toBe('failed')
  })
})

describe('checkLabel', () => {
  it('没检查过时写“未检查”', () => {
    expect(checkLabel('校验', null)).toBe('校验：未检查')
  })

  it('带上结果，过期时标注', () => {
    expect(checkLabel('预览', base)).toBe('预览：通过')
    expect(checkLabel('预览', { ...base, status: 'failed' })).toBe('预览：失败')
    expect(checkLabel('预览', { ...base, stale: true })).toBe('预览：通过（已过期）')
  })
})
