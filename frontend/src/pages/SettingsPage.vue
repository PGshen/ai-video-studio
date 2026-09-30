<script setup lang="ts">
/**
 * 设置页外壳（计划 M5 T10）：子导航 + 子路由出口。四个子页在 `features/settings/`，
 * 路由见 `router.ts`（`/settings/models|styles|voice|general`）。
 */
import { RouterLink, RouterView } from 'vue-router'

const TABS = [
  { to: '/settings/models', label: '模型配置' },
  { to: '/settings/styles', label: '风格库' },
  { to: '/settings/voice', label: '语音' },
  { to: '/settings/general', label: '通用' },
] as const
</script>

<template>
  <div class="flex flex-col gap-6">
    <nav
      class="flex gap-1 border-b"
      aria-label="设置分类"
    >
      <RouterLink
        v-for="tab in TABS"
        :key="tab.to"
        :to="tab.to"
        class="text-muted-foreground hover:text-foreground -mb-px border-b-2 border-transparent px-3 py-2 text-sm"
        active-class="!border-primary !text-foreground font-medium"
      >
        {{ tab.label }}
      </RouterLink>
    </nav>
    <RouterView />
  </div>
</template>
