<script setup lang="ts">
import AppSidebar from '@/components/AppSidebar.vue'
import SiteHeader from '@/components/SiteHeader.vue'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'

// 外壳来自 shadcn-vue 的 dashboard-01 区块（侧边栏 + 顶栏），业务内容由 <router-view>
// 渲染的 src/pages 组合层填充；本文件不属于 features/，可以自由 import 两者。
</script>

<template>
  <SidebarProvider style="--sidebar-width: calc(var(--spacing) * 72); --header-height: calc(var(--spacing) * 12)">
    <AppSidebar />
    <!-- min-w-0：内容（例如设置页里的代码编辑器）比可用宽度宽时让内容区收缩，而不是把整页撑出横向滚动条。 -->
    <SidebarInset class="min-w-0">
      <SiteHeader />
      <div class="flex flex-1 flex-col gap-4 p-4">
        <router-view />
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>
