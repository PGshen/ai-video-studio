<script setup lang="ts">
/**
 * 老 manim 项目的 `animation` 阶段（Manim 已下线，ADR 0027）：只显示下线说明。
 * 阶段在 `STAGES_WITH_OWN_ACTIONS` 里，快照栏开关由工作台经 `actions` 插槽放进来。
 */
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex shrink-0 items-center justify-end gap-2">
      <slot name="actions" />
    </div>
    <p
      class="text-muted-foreground rounded border p-4 text-sm"
      data-testid="manim-retired"
    >
      Manim 动画已下线：这个老项目的动画阶段不能再对话、预览或渲染成片；选题和叙事仍可在各自阶段查看。
    </p>
  </div>
</template>
