<script setup lang="ts">
/**
 * 关键帧提示条（任务 T12）：见 `keyframeHint.ts` 顶部注释——`render_preview`
 * 的关键帧缩略图现在能在左侧对话面板看到（TD-21 已修复），`SceneList.vue`
 * 能看到通过/失败/已过期状态（TD-33 已修复），画布这里仍然只给文字提示
 * 指向对话面板，不单独嵌一份按镜头聚合的关键帧画廊。
 */
import { computed } from 'vue'
import { keyframeHint } from './keyframeHint'

const props = defineProps<{
  sceneId: string | null
}>()

const hint = computed(() => keyframeHint(props.sceneId))
</script>

<template>
  <p class="text-muted-foreground rounded border border-dashed px-3 py-2 text-xs">
    {{ hint }}
  </p>
</template>
