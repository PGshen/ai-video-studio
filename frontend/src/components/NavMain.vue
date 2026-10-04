<script setup lang="ts">
import type { Component } from 'vue'
import { useRoute } from 'vue-router'

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

interface NavItem {
  title: string
  url: string
  icon?: Component
}

defineProps<{
  items: NavItem[]
}>()

const route = useRoute()

// 当前路由落在该菜单项之下（含子路由，例如 /projects/:id/topic 属于「项目」）时高亮。
function isActive(url: string): boolean {
  return route.path === url || route.path.startsWith(`${url}/`)
}
</script>

<template>
  <SidebarGroup>
    <SidebarGroupContent class="flex flex-col gap-2">
      <SidebarMenu>
        <SidebarMenuItem
          v-for="item in items"
          :key="item.title"
        >
          <SidebarMenuButton
            :tooltip="item.title"
            :is-active="isActive(item.url)"
            class="data-[active=true]:bg-black data-[active=true]:text-white data-[active=true]:hover:bg-black data-[active=true]:hover:text-white data-[active=true]:active:bg-black data-[active=true]:active:text-white"
            as-child
          >
            <router-link :to="item.url">
              <component
                :is="item.icon"
                v-if="item.icon"
              />
              <span>{{ item.title }}</span>
            </router-link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroupContent>
  </SidebarGroup>
</template>
