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
    meta: { title: '选题池' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/pages/SettingsPage.vue'),
    meta: { title: '设置' },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
