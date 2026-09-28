import { describe, expect, it } from 'vitest'
import { parseNarrativeSceneIds } from './narrativeScenes'

describe('parseNarrativeSceneIds', () => {
  it('按出现顺序取出 scenes[].id', () => {
    const raw = JSON.stringify({
      scenes: [
        { id: 's-hook', narration: '……' },
        { id: 's-explain', narration: '……' },
      ],
    })
    expect(parseNarrativeSceneIds(raw)).toEqual(['s-hook', 's-explain'])
  })

  it('没有 scenes 字段时返回空数组', () => {
    expect(parseNarrativeSceneIds(JSON.stringify({}))).toEqual([])
  })

  it('scenes 不是数组时返回空数组', () => {
    expect(parseNarrativeSceneIds(JSON.stringify({ scenes: 'not-an-array' }))).toEqual([])
  })

  it('过滤掉没有字符串 id 的条目', () => {
    const raw = JSON.stringify({ scenes: [{ id: 's-hook' }, { id: 42 }, {}, null] })
    expect(parseNarrativeSceneIds(raw)).toEqual(['s-hook'])
  })

  it('不是合法 JSON 时把 SyntaxError 原样抛出', () => {
    expect(() => parseNarrativeSceneIds('{not json')).toThrow(SyntaxError)
  })
})
