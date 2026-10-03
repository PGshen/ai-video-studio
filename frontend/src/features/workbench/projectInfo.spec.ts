import { describe, expect, it } from 'vitest'
import type { FileEntry, IdeaOut } from '@/types/api'
import { findProjectIdea, parseStyleHeader, styleFileGroups } from './projectInfo'

function idea(id: string): IdeaOut {
  return {
    id,
    title: `选题 ${id}`,
    pitch: null,
    counterintuitive: null,
    tags: [],
    scores: {},
    status: 'idea',
    source_session_id: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
  }
}

describe('findProjectIdea', () => {
  it('按项目的 idea_id 找到关联的选题卡片', () => {
    const ideas = [idea('a'), idea('b'), idea('c')]
    expect(findProjectIdea(ideas, 'b')?.id).toBe('b')
  })

  it('没有关联卡片或列表未加载时返回 null', () => {
    expect(findProjectIdea([idea('a')], 'x')).toBeNull()
    expect(findProjectIdea([idea('a')], null)).toBeNull()
    expect(findProjectIdea(undefined, 'a')).toBeNull()
  })
})

describe('parseStyleHeader', () => {
  it('读出 frontmatter 里的 name 和 description', () => {
    const text = '---\nname: 冷色科普\ndescription: "克制、数据驱动"\n---\n\n# 正文\n'
    expect(parseStyleHeader(text)).toEqual({ name: '冷色科普', description: '克制、数据驱动' })
  })

  it('没有 frontmatter 或字段缺失时对应字段为 null', () => {
    expect(parseStyleHeader('# 只有正文')).toEqual({ name: null, description: null })
    expect(parseStyleHeader('---\nname: 仅名称\n---\n')).toEqual({ name: '仅名称', description: null })
  })

  it('未传入内容（还没读到文件）时都为 null', () => {
    expect(parseStyleHeader(undefined)).toEqual({ name: null, description: null })
  })
})

describe('styleFileGroups', () => {
  const files: FileEntry[] = [
    { path: 'style/STYLE.md', readonly: false },
    { path: 'style/references/palette.md', readonly: false },
    { path: 'style/references/typography.md', readonly: false },
    { path: 'style/exemplars/s-hook.py', readonly: false },
    { path: 'narrative/narrative.json', readonly: false },
  ]

  it('把 style/ 下的文件分成参考和范例，忽略其它目录和入口文件', () => {
    expect(styleFileGroups(files)).toEqual({
      references: ['palette.md', 'typography.md'],
      exemplars: ['s-hook.py'],
    })
  })

  it('没有风格文件时两组都为空', () => {
    expect(styleFileGroups(undefined)).toEqual({ references: [], exemplars: [] })
  })
})
