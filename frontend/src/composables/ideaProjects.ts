/** 选题卡片 ↔ 项目的关联（一对多，记在项目的 `idea_id` 上）。选题池和项目列表共用。 */

import type { ProjectOut } from '@/types/api'

/** 选题 id → 从它创建的项目数；没有项目的选题不在表里。 */
export function countProjectsByIdea(projects: readonly ProjectOut[] | undefined): Map<string, number> {
  const counts = new Map<string, number>()
  for (const project of projects ?? []) {
    if (project.idea_id) counts.set(project.idea_id, (counts.get(project.idea_id) ?? 0) + 1)
  }
  return counts
}
