import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/projects' },
  {
    path: '/projects',
    name: 'projects',
    component: () => import('@/pages/ProjectsPage.vue'),
    meta: { title: '项目' },
  },
  {
    path: '/projects/:id/:stage',
    name: 'project-workbench',
    component: () => import('@/pages/ProjectWorkbenchPage.vue'),
    meta: { title: '工作台' },
  },
  {
    path: '/ideas',
    name: 'ideas',
    component: () => import('@/pages/IdeasPage.vue'),
    meta: { title: '选题' },
  },
  {
    path: '/styles',
    name: 'styles',
    component: () => import('@/pages/StylesPage.vue'),
    meta: { title: '风格库' },
  },
  // 风格库从设置页挪到侧栏一级菜单（ADR 0019 / 计划 style-library）：旧地址继续可用。
  { path: '/settings/styles', redirect: '/styles' },
  {
    // 设置页外壳 + 三个子页（M5 T10；风格库已移出）。子页直接是 `features/settings/` 的面板；外壳
    // `pages/SettingsPage.vue` 只负责子导航。
    path: '/settings',
    name: 'settings',
    component: () => import('@/pages/SettingsPage.vue'),
    redirect: '/settings/models',
    meta: { title: '设置' },
    children: [
      {
        path: 'models',
        name: 'settings-models',
        component: () => import('@/features/settings/ModelProfilesPanel.vue'),
      },
      {
        path: 'voice',
        name: 'settings-voice',
        component: () => import('@/features/settings/VoicePanel.vue'),
      },
      {
        path: 'general',
        name: 'settings-general',
        component: () => import('@/features/settings/GeneralPanel.vue'),
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
