<script setup lang="ts">
/**
 * 工作台的三栏外壳：对话 | 画布 | 快照栏，用 reka-ui 的 `SplitterGroup`，面板之间的分隔条可拖
 * （也可用键盘调），宽度和快照栏的折叠状态由 `autoSaveId` 记在 localStorage；快照栏默认折叠
 * （首次访问没有已保存的布局，快照栏面板的默认尺寸就是折叠尺寸）。
 * 窄屏（< lg）只用 CSS 改成上下堆叠、隐藏分隔条、覆盖面板内联的 flex 尺寸——对话/画布始终是同一份
 * 挂载（跨过断点不重新挂载，不丢画布里未保存的编辑和输入框草稿）；窄屏下快照栏始终展开。
 * 三块内容都是插槽，`rail` 插槽带 `collapsed` 与 `toggle`。
 */
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { SplitterGroup, SplitterPanel, SplitterResizeHandle } from 'reka-ui'

// 折叠窄条的宽度（够放下一个图标按钮）；最小宽度也用像素，小窗口里才不会把对话/画布压到不可用。
const COLLAPSED_PX = 44

const narrow = useMediaQuery('(max-width: 1023px)')

const railPanel = ref<InstanceType<typeof SplitterPanel> | null>(null)
const railCollapsed = computed(() => (narrow.value ? false : (railPanel.value?.isCollapsed ?? true)))

function toggleRail(): void {
  if (narrow.value) return
  if (railCollapsed.value) railPanel.value?.expand()
  else railPanel.value?.collapse()
}

// 窄屏下面板的 flex 尺寸来自内联样式，必须用 `!` 覆盖。
const stackedPanel = 'max-lg:shrink-0! max-lg:grow-0! max-lg:basis-auto!'
const handleClass = 'group flex w-4 shrink-0 items-center justify-center outline-none max-lg:hidden'
const barClass =
  'bg-border group-hover:bg-primary/50 group-focus-visible:bg-primary group-data-[state=drag]:bg-primary h-10 w-1 rounded-full transition-colors'
</script>

<template>
  <SplitterGroup
    direction="horizontal"
    auto-save-id="workbench-split"
    class="h-full min-h-0 max-lg:h-auto! max-lg:min-h-max max-lg:flex-col! max-lg:gap-4"
  >
    <SplitterPanel
      size-unit="px"
      :min-size="280"
      class="flex min-h-0 min-w-0 max-lg:h-[32rem]"
      :class="stackedPanel"
    >
      <slot name="chat" />
    </SplitterPanel>
    <SplitterResizeHandle :class="handleClass">
      <div :class="barClass" />
    </SplitterResizeHandle>
    <SplitterPanel
      size-unit="px"
      :min-size="320"
      class="flex min-h-0 min-w-0 flex-col max-lg:min-h-[32rem]"
      :class="stackedPanel"
    >
      <slot name="canvas" />
    </SplitterPanel>
    <SplitterResizeHandle :class="handleClass">
      <div :class="barClass" />
    </SplitterResizeHandle>
    <SplitterPanel
      ref="railPanel"
      size-unit="px"
      :default-size="COLLAPSED_PX"
      :collapsed-size="COLLAPSED_PX"
      :min-size="240"
      collapsible
      class="flex min-h-0 min-w-0 flex-col max-lg:min-h-[24rem]"
      :class="stackedPanel"
    >
      <slot
        name="rail"
        :collapsed="railCollapsed"
        :toggle="toggleRail"
      />
    </SplitterPanel>
  </SplitterGroup>
</template>
