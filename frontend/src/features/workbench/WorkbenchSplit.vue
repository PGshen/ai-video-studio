<script setup lang="ts">
/**
 * 工作台的三栏外壳：对话 | 画布 | 快照栏。lg 以上用 reka-ui 的 `SplitterGroup`，面板之间的分隔条可拖（也可用
 * 键盘调），宽度和快照栏的折叠状态由 `autoSaveId` 记在 localStorage；快照栏默认折叠（首次访问
 * 没有已保存的布局，快照栏面板的默认尺寸就是折叠尺寸）。窄屏（< lg）不用分隔条，三块上下堆叠，
 * 快照栏始终展开。三块内容都是插槽，`rail` 插槽带 `collapsed` 与 `toggle`。
 */
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { SplitterGroup, SplitterPanel, SplitterResizeHandle } from 'reka-ui'

const narrow = useMediaQuery('(max-width: 1023px)')

const railPanel = ref<InstanceType<typeof SplitterPanel> | null>(null)
const railCollapsed = computed(() => (narrow.value ? false : (railPanel.value?.isCollapsed ?? true)))

function toggleRail(): void {
  if (narrow.value) return
  if (railCollapsed.value) railPanel.value?.expand()
  else railPanel.value?.collapse()
}
</script>

<template>
  <div
    v-if="narrow"
    class="flex min-h-max flex-col gap-4"
  >
    <div class="flex h-[32rem] min-h-0">
      <slot name="chat" />
    </div>
    <div class="flex min-h-[32rem] flex-col">
      <slot name="canvas" />
    </div>
    <div class="flex min-h-[24rem] flex-col">
      <slot
        name="rail"
        :collapsed="false"
        :toggle="toggleRail"
      />
    </div>
  </div>
  <SplitterGroup
    v-else
    direction="horizontal"
    auto-save-id="workbench-split"
    class="h-full min-h-0"
  >
    <SplitterPanel
      :default-size="46"
      :min-size="25"
      class="flex min-h-0 min-w-0"
    >
      <slot name="chat" />
    </SplitterPanel>
    <SplitterResizeHandle class="group flex w-4 shrink-0 items-center justify-center outline-none">
      <div class="bg-border group-hover:bg-primary/50 group-focus-visible:bg-primary group-data-[state=drag]:bg-primary h-10 w-1 rounded-full transition-colors" />
    </SplitterResizeHandle>
    <SplitterPanel
      :default-size="50"
      :min-size="25"
      class="flex min-h-0 min-w-0 flex-col"
    >
      <slot name="canvas" />
    </SplitterPanel>
    <SplitterResizeHandle class="group flex w-4 shrink-0 items-center justify-center outline-none">
      <div class="bg-border group-hover:bg-primary/50 group-focus-visible:bg-primary group-data-[state=drag]:bg-primary h-10 w-1 rounded-full transition-colors" />
    </SplitterResizeHandle>
    <SplitterPanel
      ref="railPanel"
      :default-size="4"
      :collapsed-size="4"
      :min-size="20"
      collapsible
      class="flex min-h-0 min-w-0 flex-col"
    >
      <slot
        name="rail"
        :collapsed="railCollapsed"
        :toggle="toggleRail"
      />
    </SplitterPanel>
  </SplitterGroup>
</template>
