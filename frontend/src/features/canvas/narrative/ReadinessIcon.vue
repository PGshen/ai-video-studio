<script setup lang="ts">
/**
 * 叙事能否定稿的状态图标：悬停或键盘聚焦时弹出气泡，内容是定稿前提的满足情况
 * （校验通过、全部配音、对齐覆盖率达标，见 `timingStatus.computeReadiness`）。
 * 原来是画布顶部的一条提示条，现在并进标签行（同选题画布的 `BriefStatusIcon`）。
 * 这只是提示，后端 `finalize` 不强制这些条件。
 */
import { computed } from 'vue'
import { CircleCheckIcon, TriangleAlertIcon } from '@lucide/vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { Readiness } from './timingStatus'

const props = defineProps<{
  readiness: Readiness
  sceneCount: number
  /** 平均对齐覆盖率（如 `'100%'`）；还没有任何配音时为 null。 */
  coverageLabel: string | null
  /** `timing.json` 解析失败的原因；没问题时为 null。 */
  timingError: string | null
}>()

const headline = computed(() =>
  props.readiness.ready
    ? `可以定稿：${props.sceneCount} 个镜头全部校验通过并已配音，对齐覆盖率 ${props.coverageLabel}。`
    : '暂不满足定稿条件',
)
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <Tooltip>
      <TooltipTrigger as-child>
        <button
          type="button"
          class="hover:bg-muted flex size-7 items-center justify-center rounded"
          data-testid="readiness"
          :data-ready="readiness.ready"
          :aria-label="headline"
        >
          <CircleCheckIcon
            v-if="readiness.ready"
            class="size-4 text-emerald-600"
          />
          <TriangleAlertIcon
            v-else
            class="size-4 text-amber-600"
          />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="bottom"
        align="end"
        class="max-w-xs text-left"
      >
        <p>{{ headline }}</p>
        <ul
          v-if="!readiness.ready && readiness.reasons.length"
          class="mt-1 list-disc pl-4"
        >
          <li
            v-for="reason in readiness.reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
        <p
          v-if="!readiness.ready && coverageLabel"
          class="mt-1 opacity-80"
        >
          当前对齐覆盖率 {{ coverageLabel }}
        </p>
        <p
          v-if="timingError"
          class="mt-1"
        >
          解析 timing.json 失败：{{ timingError }}
        </p>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
