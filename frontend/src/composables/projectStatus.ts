/** 项目状态的显示文案；项目列表、卡片和工作台的项目信息共用。 */
import type { ProjectStatus } from '@/types/api'

export const STATUS_TEXT: Record<ProjectStatus, string> = {
  active: '进行中',
  completed: '已完成',
  abandoned: '已废弃',
}
