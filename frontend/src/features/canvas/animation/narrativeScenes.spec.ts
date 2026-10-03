import { describe, expect, it } from 'vitest'
import { parseNarrativeSceneIds, parseNarrativeScenes } from './narrativeScenes'

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

describe('parseNarrativeScenes', () => {
  it('取出每个镜头的旁白、画面意图和 beats，缺失字段用空串', () => {
    const raw = JSON.stringify({
      scenes: [
        {
          id: 's-hook',
          narration: '旁白',
          visual_intent: '意图',
          beats: [
            { cue_text: '词', visual_action: '动作', emphasis: '重点', transition: 'reveal' },
            { cue_text: '只有词' },
          ],
        },
        { id: 's-bare' },
        { id: 42 },
      ],
    })
    expect(parseNarrativeScenes(raw)).toEqual([
      {
        id: 's-hook',
        narration: '旁白',
        visualIntent: '意图',
        beats: [
          { cueText: '词', visualAction: '动作', emphasis: '重点', transition: 'reveal' },
          { cueText: '只有词', visualAction: '', emphasis: '', transition: '' },
        ],
      },
      { id: 's-bare', narration: '', visualIntent: '', beats: [] },
    ])
  })

  it('没有 scenes 时返回空数组，不是合法 JSON 时抛 SyntaxError', () => {
    expect(parseNarrativeScenes('{}')).toEqual([])
    expect(() => parseNarrativeScenes('{no')).toThrow(SyntaxError)
  })
})
