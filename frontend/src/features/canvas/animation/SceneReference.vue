<script setup lang="ts">
/**
 * 编辑器上方的参考区：标签“预览”（`KeyframeStrip`，最近一次 `render_preview`
 * 的关键帧）/“镜头 Beats”（`SceneBeats`，叙事里这个镜头的描述），用来对照
 * 下面的代码。当前标签由父组件持有（`v-model:tab`），切换镜头时保持不变。
 */
import KeyframeStrip from './KeyframeStrip.vue'
import SceneBeats from './SceneBeats.vue'
import type { NarrativeSceneInfo } from './narrativeScenes'

export type ReferenceTab = 'preview' | 'beats'

defineProps<{
  projectId: string
  sceneId: string
  images: readonly string[]
  stale: boolean
  narrativeScene: NarrativeSceneInfo | null
}>()

const tab = defineModel<ReferenceTab>('tab', { required: true })
</script>

<template>
  <div
    class="flex flex-col gap-2"
    data-testid="scene-reference"
  >
    <div
      class="flex items-center gap-1 text-xs"
      role="tablist"
    >
      <button
        type="button"
        role="tab"
        class="rounded px-2.5 py-1 whitespace-nowrap"
        :class="tab === 'preview' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        :aria-selected="tab === 'preview'"
        @click="tab = 'preview'"
      >
        预览{{ images.length ? `（${images.length}）` : '' }}
      </button>
      <button
        type="button"
        role="tab"
        class="rounded px-2.5 py-1 whitespace-nowrap"
        :class="tab === 'beats' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        :aria-selected="tab === 'beats'"
        @click="tab = 'beats'"
      >
        镜头 Beats{{ narrativeScene?.beats.length ? `（${narrativeScene.beats.length}）` : '' }}
      </button>
    </div>

    <KeyframeStrip
      v-if="tab === 'preview'"
      :project-id="projectId"
      :scene-id="sceneId"
      :images="images"
      :stale="stale"
    />
    <SceneBeats
      v-else
      :scene="narrativeScene"
    />
  </div>
</template>
