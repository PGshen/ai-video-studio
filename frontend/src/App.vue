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
    <SidebarInset>
      <SiteHeader />
      <div class="flex flex-1 flex-col gap-4 p-4">
        <router-view />
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>
