<script setup lang="ts">
/**
 * 工作台的三栏外壳：对话 | 画布 | 快照栏，用 reka-ui 的 `SplitterGroup`，面板之间的分隔条可拖
 * （也可用键盘调），宽度和快照栏的折叠状态由 `autoSaveId` 记在 localStorage；快照栏默认整栏隐藏
 * （折叠尺寸是 0，首次访问没有已保存的布局，面板的默认尺寸就是折叠尺寸），折叠时它前面的分隔条也隐藏；
 * 展开入口在画布右上角（`canvas` 插槽带 `railCollapsed`/`toggleRail`/`narrow`，由画布一侧放按钮）。
 * 窄屏（< lg）只用 CSS 改成上下堆叠、隐藏分隔条、覆盖面板内联的 flex 尺寸——对话/画布始终是同一份
 * 挂载（跨过断点不重新挂载，不丢画布里未保存的编辑和输入框草稿）；窄屏下快照栏始终展开。
 * 三块内容都是插槽，`rail` 插槽带 `collapsed` 与 `toggle`；点开关时面板宽度有 200ms 过渡，
 * `rail` 插槽的 `collapsed` 在收起时延迟到动画结束才变 true（内容被滑窄裁掉，不是瞬间消失）。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { SplitterGroup, SplitterPanel, SplitterResizeHandle } from 'reka-ui'

// 最小宽度用像素，小窗口里才不会把对话/画布压到不可用。
const narrow = useMediaQuery('(max-width: 1023px)')

const railPanel = ref<InstanceType<typeof SplitterPanel> | null>(null)
const railCollapsed = computed(() => (narrow.value ? false : (railPanel.value?.isCollapsed ?? true)))

// 展开/收起快照栏时给三个面板的 flex-grow 加过渡；只在点开关的这一小段时间里开，
// 拖分隔条和窗口缩放时不能有过渡（会拖不跟手）。
const ANIM_MS = 200
const animating = ref(false)
// 传给 `rail` 插槽的「视觉折叠」：动画期间固定为 false（展开立刻显示内容，收起时内容留到动画结束），
// 这样收起过程中快照栏是被滑窄裁掉而不是瞬间消失；动画之外就是真实的折叠状态。
let timer: ReturnType<typeof setTimeout> | undefined

function toggleRail(): void {
  if (narrow.value) return
  const expanding = railCollapsed.value
  clearTimeout(timer)
  animating.value = true
  if (expanding) railPanel.value?.expand()
  else railPanel.value?.collapse()
  timer = setTimeout(() => {
    animating.value = false
  }, ANIM_MS + 50)
}
onBeforeUnmount(() => clearTimeout(timer))
const railSlotCollapsed = computed(() => (narrow.value || animating.value ? false : railCollapsed.value))

// 窄屏下面板的 flex 尺寸来自内联样式，必须用 `!` 覆盖。
const stackedPanel = 'max-lg:shrink-0! max-lg:grow-0! max-lg:basis-auto!'
const animClass = computed(() =>
  animating.value ? 'transition-[flex-grow] duration-200 ease-out motion-reduce:transition-none' : '',
)
const handleClass = 'group flex w-4 shrink-0 items-center justify-center outline-none max-lg:hidden'
const barClass =
  'bg-border group-hover:bg-primary/50 group-focus-visible:bg-primary group-data-[state=drag]:bg-primary h-10 w-1 rounded-full transition-colors'
</script>

<template>
  <SplitterGroup
    direction="horizontal"
    auto-save-id="workbench-split-v2"
    class="h-full min-h-0 max-lg:h-auto! max-lg:min-h-max max-lg:flex-col! max-lg:gap-4"
  >
    <SplitterPanel
      size-unit="px"
      :min-size="280"
      class="flex min-h-0 min-w-0 max-lg:h-[32rem]"
      :class="[stackedPanel, animClass]"
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
      :class="[stackedPanel, animClass]"
    >
      <slot
        name="canvas"
        :rail-collapsed="railCollapsed"
        :toggle-rail="toggleRail"
        :narrow="narrow"
      />
    </SplitterPanel>
    <SplitterResizeHandle :class="[handleClass, railCollapsed && !narrow && 'hidden']">
      <div :class="barClass" />
    </SplitterResizeHandle>
    <SplitterPanel
      ref="railPanel"
      size-unit="px"
      :default-size="0"
      :collapsed-size="0"
      :min-size="240"
      collapsible
      class="flex min-h-0 min-w-0 flex-col overflow-hidden max-lg:min-h-[24rem]"
      :class="[stackedPanel, animClass]"
    >
      <slot
        name="rail"
        :collapsed="railSlotCollapsed"
        :toggle="toggleRail"
      />
    </SplitterPanel>
  </SplitterGroup>
</template>
