<script setup lang="ts">
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'

interface User {
  name: string
  email: string
  avatar: string
}

defineProps<{
  user: User
}>()
</script>

<template>
  <!-- 单人本地使用，不需要账号切换/登出菜单，只展示当前用户信息。 -->
  <SidebarMenu>
    <SidebarMenuItem>
      <SidebarMenuButton
        size="lg"
        class="cursor-default hover:bg-transparent"
      >
        <Avatar class="h-8 w-8 rounded-lg">
          <AvatarFallback class="rounded-lg">
            {{ user.name.slice(0, 2).toUpperCase() }}
          </AvatarFallback>
        </Avatar>
        <div class="grid flex-1 text-left text-sm leading-tight">
          <span class="truncate font-medium">{{ user.name }}</span>
          <span class="text-muted-foreground truncate text-xs">{{ user.email }}</span>
        </div>
      </SidebarMenuButton>
    </SidebarMenuItem>
  </SidebarMenu>
</template>
