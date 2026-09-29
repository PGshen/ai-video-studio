import { describe, expect, it } from 'vitest'
import { isIdeaWriteTool } from '@/composables/ideaEvents'

describe('isIdeaWriteTool', () => {
  it('识别 create_idea / update_idea，兼容 Claude 侧的 mcp__<server>__ 前缀', () => {
    expect(isIdeaWriteTool('create_idea')).toBe(true)
    expect(isIdeaWriteTool('update_idea')).toBe(true)
    expect(isIdeaWriteTool('mcp__studio__create_idea')).toBe(true)
    expect(isIdeaWriteTool('mcp__studio__update_idea')).toBe(true)
  })

  it('不把只读工具或名字相近的工具算进来', () => {
    expect(isIdeaWriteTool('list_ideas')).toBe(false)
    expect(isIdeaWriteTool('mcp__studio__list_ideas')).toBe(false)
    expect(isIdeaWriteTool('my_create_idea')).toBe(false)
    expect(isIdeaWriteTool('write_file')).toBe(false)
  })
})
