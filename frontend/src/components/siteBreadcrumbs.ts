/**
 * 顶栏面包屑的纯函数：由路由信息（和工作台的项目名）算出面包屑条目。
 * 最后一项是当前页（无 `to`），其余带 `to` 可点击。
 */
import { STAGE_TITLES } from '@/components/session/suggestionFlow'

export interface Crumb {
  label: string
  to?: string
}

export interface BreadcrumbInput {
  routeName: string | undefined
  /** 路由 meta.title，例如「项目」「设置」。 */
  title: string
  projectId?: string
  projectTitle?: string
  stage?: string
}

export function buildBreadcrumbs(input: BreadcrumbInput): Crumb[] {
  if (input.routeName === 'project-workbench' && input.projectId) {
    const stage = input.stage ?? ''
    return [
      { label: '项目', to: '/projects' },
      { label: input.projectTitle ?? '…' },
      { label: STAGE_TITLES[stage] ?? (stage || input.title) },
    ]
  }
  return input.title ? [{ label: input.title }] : []
}
