import { describe, expect, it } from 'vitest'
import type { SceneChecksOut } from '@/types/api'
import { computeSceneStatuses, scenePath } from './sceneStatus'

const PASSED: SceneChecksOut = {
  validate_scenes: { status: 'passed', stale: false, checked_at: '2026-09-29T00:00:00Z', images: [] },
  render_preview: { status: 'not_checked', stale: false, checked_at: null, images: [] },
}

describe('scenePath', () => {
  it('拼出 animation/scenes/<id>.py', () => {
    expect(scenePath('s-hook')).toBe('animation/scenes/s-hook.py')
  })
})

describe('computeSceneStatuses', () => {
  it('按叙事顺序标出每个镜头代码是否存在，没有检查数据时留 null（TD-33）', () => {
    const result = computeSceneStatuses(
      ['s-hook', 's-explain'],
      ['animation/scenes/s-hook.py', 'upstream/narrative/narrative.json'],
    )
    expect(result).toEqual([
      {
        id: 's-hook',
        path: 'animation/scenes/s-hook.py',
        exists: true,
        validateScenes: null,
        renderPreview: null,
      },
      {
        id: 's-explain',
        path: 'animation/scenes/s-explain.py',
        exists: false,
        validateScenes: null,
        renderPreview: null,
      },
    ])
  })

  it('没有镜头时返回空数组', () => {
    expect(computeSceneStatuses([], ['animation/scenes/s-hook.py'])).toEqual([])
  })

  it('没有任何文件时全部标记为不存在', () => {
    const result = computeSceneStatuses(['s-hook'], [])
    expect(result[0]?.exists).toBe(false)
  })

  it('按镜头 id 把检查结果合并进对应的 SceneStatus（TD-33）', () => {
    const result = computeSceneStatuses(['s-hook', 's-explain'], ['animation/scenes/s-hook.py'], {
      's-hook': PASSED,
    })

    expect(result[0]?.validateScenes).toEqual(PASSED.validate_scenes)
    expect(result[0]?.renderPreview).toEqual(PASSED.render_preview)
    expect(result[1]?.validateScenes).toBeNull()
  })
})
