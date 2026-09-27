<script setup lang="ts">
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

// 项目列表 + 新建对话框由 T13 实现（对接 /api/projects）。T11 只搭骨架，
// 保证 pages/ProjectsPage 能挂载真实的 features/projects 组件。
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>项目</CardTitle>
      <CardDescription>项目列表与新建功能将在 T13 接入。</CardDescription>
    </CardHeader>
  </Card>
</template>
