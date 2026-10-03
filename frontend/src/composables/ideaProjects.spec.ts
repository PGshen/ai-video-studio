import { describe, expect, it } from 'vitest'
import type { ProjectOut } from '@/types/api'
import { countProjectsByIdea } from './ideaProjects'

function project(id: string, ideaId: string | null): ProjectOut {
  return { id, title: id, idea_id: ideaId, current_stage: 'topic', settings: {}, completed_at: null }
}

describe('countProjectsByIdea', () => {
  it('按 idea_id 统计，没有关联选题的项目不计', () => {
    const counts = countProjectsByIdea([project('p1', 'a'), project('p2', 'a'), project('p3', 'b'), project('p4', null)])
    expect(counts.get('a')).toBe(2)
    expect(counts.get('b')).toBe(1)
    expect(counts.size).toBe(2)
  })
  it('没有数据时是空表', () => {
    expect(countProjectsByIdea(undefined).size).toBe(0)
  })
})
