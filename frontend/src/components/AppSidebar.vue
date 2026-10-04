<script setup lang="ts">
import { Sparkles } from '@lucide/vue'

import NavMain from '@/components/NavMain.vue'
import NavUser from '@/components/NavUser.vue'
import { NAV_MAIN } from '@/components/navItems'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

// dashboard-01 的原始 demo 内容（图表、数据表、云端文档分组）已按 T11 简报要求移除，
// 只保留外壳布局；导航项对应本项目真实的路由（见 src/router.ts）。
const data = {
  user: {
    name: 'pengguishen',
    email: 'pgs1108pgs@gmail.com',
    avatar: '',
  },
  navMain: NAV_MAIN,
}
</script>

<template>
  <Sidebar collapsible="offcanvas">
    <SidebarHeader>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            as-child
            class="data-[slot=sidebar-menu-button]:!p-1.5"
          >
            <router-link to="/projects">
              <Sparkles class="!size-5" />
              <span class="text-base font-semibold">AI Video Studio</span>
            </router-link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarHeader>
    <SidebarContent>
      <NavMain :items="data.navMain" />
    </SidebarContent>
    <SidebarFooter>
      <NavUser :user="data.user" />
    </SidebarFooter>
  </Sidebar>
</template>
