<script setup lang="ts">
import { useRoute } from 'vue-router'

// 工作台外壳（阶段导航、会话面板、通用文件画布、快照时间线）由 T13/T14 实现。
const route = useRoute()
</script>

<template>
  <div class="text-muted-foreground text-sm">
    项目 {{ route.params.id }} · 阶段 {{ route.params.stage }} 的工作台将在 T13/T14 接入。
  </div>
</template>
