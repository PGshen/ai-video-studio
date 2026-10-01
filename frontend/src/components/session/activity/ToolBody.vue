<script setup lang="ts">
/** 按渲染种类分发工具正文（设计 §5）；没有专属正文的种类走通用样式。 */
import type { ToolCallItem } from '@/composables/useSessionStream'
import type { ToolView } from '@/components/session/toolPresentation'
import GenericBody from './tool-bodies/GenericBody.vue'

defineProps<{ item: ToolCallItem; view: ToolView; projectId: string | null }>()
</script>

<template>
  <GenericBody
    :item="item"
    :project-id="projectId"
  />
</template>
