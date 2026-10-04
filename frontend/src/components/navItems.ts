import { FolderKanban, Lightbulb, Palette, Settings } from '@lucide/vue'
import type { Component } from 'vue'

export interface NavItem {
  title: string
  url: string
  icon: Component
}

/** 侧栏一级菜单；对应真实路由见 `src/router.ts`。 */
export const NAV_MAIN: NavItem[] = [
  { title: '选题', url: '/ideas', icon: Lightbulb },
  { title: '项目', url: '/projects', icon: FolderKanban },
  { title: '风格库', url: '/styles', icon: Palette },
  { title: '设置', url: '/settings', icon: Settings },
]
