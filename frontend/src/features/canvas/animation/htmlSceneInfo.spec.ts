import { describe, expect, it } from 'vitest'
import { sceneInfoFromSection } from './htmlSceneInfo'

describe('sceneInfoFromSection', () => {
  it('maps the section label to the visual intent and beats to cue texts', () => {
    const info = sceneInfoFromSection({
      id: 's-hook',
      label: '开场',
      start: 0,
      end: 3,
      beats: [{ start: 0.4, end: 1.4, cue_text: '第一句' }],
    })
    expect(info).toEqual({
      id: 's-hook',
      narration: '',
      visualIntent: '开场',
      beats: [{ cueText: '第一句', visualAction: '', emphasis: '', transition: '' }],
    })
  })
})
