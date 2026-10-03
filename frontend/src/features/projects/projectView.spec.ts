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
    abandoned_at: null,
    status: 'active',
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
  it('直接用后端给的状态', () => {
    expect(projectStatus(project())).toBe('active')
    expect(projectStatus(project({ status: 'completed' }))).toBe('completed')
    expect(projectStatus(project({ status: 'abandoned' }))).toBe('abandoned')
  })

  it('状态文案', () => {
    expect(statusText('active')).toBe('进行中')
    expect(statusText('completed')).toBe('已完成')
    expect(statusText('abandoned')).toBe('已废弃')
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
    project({ id: 'p3', title: '哈希表', current_stage: 'animation', completed_at: '2026-10-01T00:00:00Z', status: 'completed' }),
    project({ id: 'p5', title: '废弃的', abandoned_at: '2026-10-02T00:00:00Z', status: 'abandoned' }),
  ]
  const ideaOf = ideasById([idea({ pitch: '结局决定记忆', tags: ['认知偏差'] })])

  it('不筛选时全部返回', () => {
    expect(filterProjects(projects, ideaOf, all)).toHaveLength(4)
  })
  it('按阶段筛选', () => {
    expect(filterProjects(projects, ideaOf, { ...all, stage: 'narrative' }).map((p) => p.id)).toEqual(['p2'])
  })
  it('按状态筛选', () => {
    expect(filterProjects(projects, ideaOf, { ...all, status: 'completed' }).map((p) => p.id)).toEqual(['p3'])
    expect(filterProjects(projects, ideaOf, { ...all, status: 'abandoned' }).map((p) => p.id)).toEqual(['p5'])
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
