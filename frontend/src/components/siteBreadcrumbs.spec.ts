import { describe, expect, it } from 'vitest'
import { buildBreadcrumbs } from './siteBreadcrumbs'

describe('buildBreadcrumbs', () => {
  it('plain pages show only their title', () => {
    expect(buildBreadcrumbs({ routeName: 'projects', title: '项目' })).toEqual([{ label: '项目' }])
    expect(buildBreadcrumbs({ routeName: 'settings-models', title: '设置' })).toEqual([{ label: '设置' }])
  })

  it('workbench links back to the projects list and shows project + stage', () => {
    expect(
      buildBreadcrumbs({
        routeName: 'project-workbench',
        title: '工作台',
        projectId: 'p1',
        projectTitle: '哈希表 vs B+树',
        stage: 'narrative',
      }),
    ).toEqual([{ label: '项目', to: '/projects' }, { label: '哈希表 vs B+树' }, { label: '叙事' }])
  })

  it('falls back to a placeholder while the project is loading', () => {
    const crumbs = buildBreadcrumbs({
      routeName: 'project-workbench',
      title: '工作台',
      projectId: 'p1',
      stage: 'topic',
    })
    expect(crumbs[1]).toEqual({ label: '…' })
  })

  it('unknown route without a title yields no crumbs', () => {
    expect(buildBreadcrumbs({ routeName: undefined, title: '' })).toEqual([])
  })
})
