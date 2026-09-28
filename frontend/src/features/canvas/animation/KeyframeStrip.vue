<script setup lang="ts">
/**
 * 关键帧提示条（任务 T12）：见 `keyframeHint.ts` 顶部注释——`render_preview`
 * 的关键帧图片字节内容目前没有被后端持久化（TD-21），画布这里只能给出
 * 文字提示，指向真正能看到"含 N 张图片"计数的地方（左侧对话面板）。
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
