<script setup lang="ts">
/**
 * 按渲染种类分发工具正文（设计 §5）。出错时各正文自己决定怎么显示（`ErrorPane`；`bash` 的
 * 输出本身就是结果，直接显示），这里不叠加，避免错误出现两次。
 */
import type { Component } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import type { ToolStatus, ToolView } from '@/components/session/toolPresentation'
import BashBody from './tool-bodies/BashBody.vue'
import GenericBody from './tool-bodies/GenericBody.vue'
import GlobBody from './tool-bodies/GlobBody.vue'
import GrepBody from './tool-bodies/GrepBody.vue'
import ReadBody from './tool-bodies/ReadBody.vue'
import WebFetchBody from './tool-bodies/WebFetchBody.vue'
import WebSearchBody from './tool-bodies/WebSearchBody.vue'
import WriteBody from './tool-bodies/WriteBody.vue'

defineProps<{
  item: ToolCallItem
  view: ToolView
  status: ToolStatus
  projectId: string | null
}>()

const BODIES: Record<ToolView['kind'], Component> = {
  read: ReadBody,
  write: WriteBody,
  glob: GlobBody,
  grep: GrepBody,
  bash: BashBody,
  'web-search': WebSearchBody,
  'web-fetch': WebFetchBody,
  generic: GenericBody,
}
</script>

<template>
  <component
    :is="BODIES[view.kind]"
    :item="item"
    :view="view"
    :status="status"
    :project-id="projectId"
  />
</template>
