import { describe, expect, it } from 'vitest'
import { computeSceneStatuses, scenePath } from './sceneStatus'

describe('scenePath', () => {
  it('拼出 animation/scenes/<id>.py', () => {
    expect(scenePath('s-hook')).toBe('animation/scenes/s-hook.py')
  })
})

describe('computeSceneStatuses', () => {
  it('按叙事顺序标出每个镜头代码是否存在', () => {
    const result = computeSceneStatuses(
      ['s-hook', 's-explain'],
      ['animation/scenes/s-hook.py', 'upstream/narrative/narrative.json'],
    )
    expect(result).toEqual([
      { id: 's-hook', path: 'animation/scenes/s-hook.py', exists: true },
      { id: 's-explain', path: 'animation/scenes/s-explain.py', exists: false },
    ])
  })

  it('没有镜头时返回空数组', () => {
    expect(computeSceneStatuses([], ['animation/scenes/s-hook.py'])).toEqual([])
  })

  it('没有任何文件时全部标记为不存在', () => {
    const result = computeSceneStatuses(['s-hook'], [])
    expect(result).toEqual([{ id: 's-hook', path: 'animation/scenes/s-hook.py', exists: false }])
  })
})
