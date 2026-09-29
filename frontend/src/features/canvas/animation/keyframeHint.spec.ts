import { describe, expect, it } from 'vitest'
import { keyframeHint } from './keyframeHint'

describe('keyframeHint', () => {
  it('未选中镜头时给出通用提示', () => {
    expect(keyframeHint(null)).toContain('选择一个镜头')
  })

  it('选中镜头时点名该镜头 id 和 render_preview 工具', () => {
    const text = keyframeHint('s-explain')
    expect(text).toContain('s-explain')
    expect(text).toContain('render_preview')
  })
})
