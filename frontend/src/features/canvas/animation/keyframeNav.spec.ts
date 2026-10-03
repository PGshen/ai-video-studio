import { describe, expect, it } from 'vitest'
import { stepKeyframe } from './keyframeNav'

describe('stepKeyframe', () => {
  it('前后移动一张', () => {
    expect(stepKeyframe(1, 1, 3)).toBe(2)
    expect(stepKeyframe(1, -1, 3)).toBe(0)
  })

  it('到头尾时停住，不循环', () => {
    expect(stepKeyframe(2, 1, 3)).toBe(2)
    expect(stepKeyframe(0, -1, 3)).toBe(0)
  })

  it('没有图片时保持 0', () => {
    expect(stepKeyframe(0, 1, 0)).toBe(0)
  })
})
