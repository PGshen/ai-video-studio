/**
 * 项目列表的纯逻辑：状态判断、关联选题查找、筛选。组件只做展示和事件，判断都在这里，方便单测。
 * 项目列表接口只给基础字段，选题的卖点/标签/评分靠 `idea_id` 关联过来。
 */

import type { IdeaOut, ProjectOut } from '@/types/api'

export type ProjectStatus = 'active' | 'done'
export type StatusFilter = 'all' | ProjectStatus

export function projectStatus(project: ProjectOut): ProjectStatus {
  return project.completed_at ? 'done' : 'active'
}

export function statusText(status: ProjectStatus): string {
  return status === 'done' ? '已完成' : '进行中'
}

/** 选题 id → 选题；项目靠自己的 `idea_id` 找关联选题（一张选题可以对应多个项目）。 */
export function ideasById(ideas: readonly IdeaOut[] | undefined): Map<string, IdeaOut> {
  return new Map((ideas ?? []).map((idea) => [idea.id, idea]))
}

export interface ProjectFilter {
  query: string
  /** `null` 不限阶段；否则是 `current_stage` 的值。 */
  stage: string | null
  status: StatusFilter
  /** `null` 不限选题；否则只留从这张选题卡片创建的项目。 */
  ideaId: string | null
}

export function filterProjects(
  projects: readonly ProjectOut[],
  ideas: ReadonlyMap<string, IdeaOut>,
  filter: ProjectFilter,
): ProjectOut[] {
  const needle = filter.query.trim().toLowerCase()
  return projects.filter((project) => {
    if (filter.ideaId !== null && project.idea_id !== filter.ideaId) return false
    if (filter.stage !== null && project.current_stage !== filter.stage) return false
    if (filter.status !== 'all' && projectStatus(project) !== filter.status) return false
    if (!needle) return true
    const idea = project.idea_id ? ideas.get(project.idea_id) : undefined
    const haystacks = [project.title, idea?.pitch ?? '', ...(idea?.tags ?? [])]
    return haystacks.some((text) => text.toLowerCase().includes(needle))
  })
}
