import { describe, expect, it } from 'vitest'
import {
  duplicateSceneIds,
  normalizeAlignmentText,
  parseNarrativeDoc,
  sceneIssues,
  type NarrativeScene,
} from './narrativeDoc'

function beat(cue_text: string, transition = 'continue') {
  return { cue_text, visual_action: '动作', emphasis: '要点', transition }
}

function scene(overrides: Partial<NarrativeScene> = {}): NarrativeScene {
  return {
    id: 's-a',
    narration: '甲乙，丙丁。',
    visual_intent: '意图',
    beats: [beat('甲乙，'), beat('丙丁。')],
    ...overrides,
  }
}

describe('parseNarrativeDoc', () => {
  it('按出现顺序解析完整字段', () => {
    const raw = JSON.stringify({
      scenes: [
        {
          id: 's-hook',
          narration: '你好',
          visual_intent: '开场',
          beats: [{ cue_text: '你好', visual_action: '淡入', emphasis: '问候', transition: 'reveal' }],
        },
        { id: 's-end', narration: '再见', visual_intent: '收束', beats: [] },
      ],
    })
    expect(parseNarrativeDoc(raw)).toEqual([
      {
        id: 's-hook',
        narration: '你好',
        visual_intent: '开场',
        beats: [{ cue_text: '你好', visual_action: '淡入', emphasis: '问候', transition: 'reveal' }],
      },
      { id: 's-end', narration: '再见', visual_intent: '收束', beats: [] },
    ])
  })

  it('字段缺失时用空串/空数组，过滤没有字符串 id 的镜头', () => {
    const raw = JSON.stringify({ scenes: [{ id: 's-a' }, { id: 7 }, null, { id: 's-b', beats: [1] }] })
    expect(parseNarrativeDoc(raw)).toEqual([
      { id: 's-a', narration: '', visual_intent: '', beats: [] },
      {
        id: 's-b',
        narration: '',
        visual_intent: '',
        beats: [{ cue_text: '', visual_action: '', emphasis: '', transition: '' }],
      },
    ])
  })

  it('没有 scenes 数组时返回空数组', () => {
    expect(parseNarrativeDoc('{}')).toEqual([])
    expect(parseNarrativeDoc('[]')).toEqual([])
    expect(parseNarrativeDoc(JSON.stringify({ scenes: 'x' }))).toEqual([])
  })

  it('不是合法 JSON 时把 SyntaxError 原样抛出', () => {
    expect(() => parseNarrativeDoc('{not json')).toThrow(SyntaxError)
  })
})

describe('normalizeAlignmentText', () => {
  it('全角标点转半角并去空白', () => {
    expect(normalizeAlignmentText('甲，乙 。\n丙：“丁”')).toBe('甲,乙.丙:"丁"')
  })
})

describe('sceneIssues', () => {
  it('合法镜头没有问题', () => {
    expect(sceneIssues(scene())).toEqual([])
  })

  it('全半角标点和空白差异不算问题，缺标点算', () => {
    expect(sceneIssues(scene({ beats: [beat('甲乙,'), beat('丙丁. ')] }))).toEqual([])
    expect(sceneIssues(scene({ beats: [beat('甲乙'), beat('丙丁')] }))).toEqual([
      'beats 的 cue_text 没有完整覆盖旁白',
    ])
  })

  it('没有 beats 时只报这一条', () => {
    expect(sceneIssues(scene({ beats: [] }))).toEqual(['还没有 beats'])
  })

  it('报出空字段和非法 transition', () => {
    const issues = sceneIssues(
      scene({
        narration: '',
        visual_intent: '',
        beats: [{ cue_text: '', visual_action: '', emphasis: '', transition: 'fade' }],
      }),
    )
    expect(issues).toEqual([
      '旁白为空',
      '缺少 visual_intent',
      'beat 1 缺少 cue_text',
      'beat 1 缺少 visual_action',
      'beat 1 缺少 emphasis',
      'beat 1 的 transition 不合法：fade',
    ])
  })
})

describe('duplicateSceneIds', () => {
  it('返回重复出现的 id（每个只报一次）', () => {
    const scenes = [scene({ id: 'a' }), scene({ id: 'b' }), scene({ id: 'a' }), scene({ id: 'a' })]
    expect(duplicateSceneIds(scenes)).toEqual(['a'])
  })

  it('没有重复时为空', () => {
    expect(duplicateSceneIds([scene({ id: 'a' }), scene({ id: 'b' })])).toEqual([])
  })
})
