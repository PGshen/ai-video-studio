import { describe, expect, it } from 'vitest'
import { canvasTabs } from './canvasTabs'

const all = { narrative: true, music: true, files: true }
const none = { narrative: false, music: false, files: false }

describe('canvasTabs', () => {
  it('讲解动画阶段：镜头 / 实时预览 / 成片，默认镜头；忽略插槽', () => {
    expect(canvasTabs('animation_html', all)).toEqual({
      tabs: ['scenes', 'preview', 'final'],
      initial: 'scenes',
    })
  })

  it('配乐与动画：有配乐插槽时多一个配乐，默认镜头', () => {
    expect(canvasTabs('produce', all)).toEqual({
      tabs: ['scenes', 'preview', 'music', 'final'],
      initial: 'scenes',
    })
    expect(canvasTabs('produce', none).tabs).toEqual(['scenes', 'preview', 'final'])
  })

  it('自由讲解：叙事在最前、文件在最后，默认实时预览', () => {
    expect(canvasTabs('free_explainer', all)).toEqual({
      tabs: ['narrative', 'scenes', 'preview', 'music', 'final', 'files'],
      initial: 'preview',
    })
    expect(canvasTabs('free_explainer', { ...all, music: false }).tabs).toEqual([
      'narrative',
      'scenes',
      'preview',
      'final',
      'files',
    ])
  })

  it('自由创作：没有叙事页（即使给了插槽），默认实时预览', () => {
    expect(canvasTabs('free_produce', all)).toEqual({
      tabs: ['scenes', 'preview', 'music', 'final', 'files'],
      initial: 'preview',
    })
  })
})
