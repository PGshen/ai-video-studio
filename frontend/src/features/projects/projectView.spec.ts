import { describe, expect, it } from 'vitest'
import type { IdeaOut, ProjectOut } from '@/types/api'
import { filterProjects, ideasById, projectStatus, statusText } from './projectView'

function project(overrides: Partial<ProjectOut> = {}): ProjectOut {
  return {
    id: 'p1',
    title: '峰终定律',
    idea_id: null,
    current_stage: 'topic',
    settings: {},
    completed_at: null,
    ...overrides,
  }
}

function idea(overrides: Partial<IdeaOut> = {}): IdeaOut {
  return {
    id: 'i1',
    title: '选题',
    pitch: '一句话卖点',
    counterintuitive: null,
    tags: ['心理学'],
    scores: {},
    status: 'idea',
    source_session_id: null,
    created_at: '2026-09-29T00:00:00Z',
    updated_at: '2026-09-29T00:00:00Z',
    ...overrides,
  }
}

const all = { query: '', stage: null, status: 'all', ideaId: null } as const

describe('projectStatus', () => {
  it('有完成时间是已完成，否则进行中', () => {
    expect(projectStatus(project())).toBe('active')
    expect(projectStatus(project({ completed_at: '2026-10-01T00:00:00Z' }))).toBe('done')
    expect(statusText('active')).toBe('进行中')
    expect(statusText('done')).toBe('已完成')
  })
})

describe('ideasById', () => {
  it('按 id 建索引', () => {
    const map = ideasById([idea(), idea({ id: 'i2' })])
    expect([...map.keys()]).toEqual(['i1', 'i2'])
    expect(ideasById(undefined).size).toBe(0)
  })
})

describe('filterProjects', () => {
  const projects = [
    project({ idea_id: 'i1' }),
    project({ id: 'p2', title: '合众无知', current_stage: 'narrative' }),
    project({ id: 'p3', title: '哈希表', current_stage: 'animation', completed_at: '2026-10-01T00:00:00Z' }),
  ]
  const ideaOf = ideasById([idea({ pitch: '结局决定记忆', tags: ['认知偏差'] })])

  it('不筛选时全部返回', () => {
    expect(filterProjects(projects, ideaOf, all)).toHaveLength(3)
  })
  it('按阶段筛选', () => {
    expect(filterProjects(projects, ideaOf, { ...all, stage: 'narrative' }).map((p) => p.id)).toEqual(['p2'])
  })
  it('按状态筛选', () => {
    expect(filterProjects(projects, ideaOf, { ...all, status: 'done' }).map((p) => p.id)).toEqual(['p3'])
    expect(filterProjects(projects, ideaOf, { ...all, status: 'active' }).map((p) => p.id)).toEqual(['p1', 'p2'])
  })
  it('关键词匹配标题，也匹配关联选题的卖点和标签，忽略大小写和首尾空白', () => {
    expect(filterProjects(projects, ideaOf, { ...all, query: ' 合众 ' }).map((p) => p.id)).toEqual(['p2'])
    expect(filterProjects(projects, ideaOf, { ...all, query: '记忆' }).map((p) => p.id)).toEqual(['p1'])
    expect(filterProjects(projects, ideaOf, { ...all, query: '认知' }).map((p) => p.id)).toEqual(['p1'])
  })
  it('按选题筛选：同一张选题的多个项目都留下', () => {
    const several = [...projects, project({ id: 'p4', title: '另一个', idea_id: 'i1' })]
    expect(filterProjects(several, ideaOf, { ...all, ideaId: 'i1' }).map((p) => p.id)).toEqual(['p1', 'p4'])
  })
  it('条件叠加', () => {
    expect(filterProjects(projects, ideaOf, { ...all, query: '哈希', stage: 'topic' })).toEqual([])
  })
})
