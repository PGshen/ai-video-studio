<script setup lang="ts">
/**
 * 选题简报的检查结果：一个状态图标，悬停或键盘聚焦时弹出气泡，内容是 `check_brief` 同一份
 * 检查结果的结论 + 错误 + 警告（计划 M4 T11；canvas-layout 把原来的提示条改成图标）。
 * 有错误时后端会拒绝定稿（计划 D4），这里只显示原因。
 */
import { computed } from 'vue'
import { CircleCheckIcon, CircleXIcon, LoaderCircleIcon, TriangleAlertIcon } from '@lucide/vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { TopicCheckOut } from '@/types/api'
import { computeBriefStatus } from './briefStatus'

const props = defineProps<{ check: TopicCheckOut | undefined }>()
const status = computed(() => computeBriefStatus(props.check))

const ICONS = {
  unknown: { icon: LoaderCircleIcon, tone: 'text-muted-foreground animate-spin' },
  ok: { icon: CircleCheckIcon, tone: 'text-emerald-600' },
  warnings: { icon: TriangleAlertIcon, tone: 'text-amber-600' },
  errors: { icon: CircleXIcon, tone: 'text-destructive' },
} as const
const presentation = computed(() => ICONS[status.value.level])
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <Tooltip>
      <TooltipTrigger as-child>
        <button
          type="button"
          class="hover:bg-muted flex size-7 items-center justify-center rounded"
          data-testid="brief-status"
          :data-level="status.level"
          :aria-label="status.headline"
        >
          <component
            :is="presentation.icon"
            class="size-4"
            :class="presentation.tone"
          />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="bottom"
        align="end"
        class="max-w-xs text-left"
      >
        <p>{{ status.headline }}</p>
        <ul
          v-if="status.errors.length"
          class="mt-1 list-disc pl-4"
        >
          <li
            v-for="message in status.errors"
            :key="message"
          >
            {{ message }}
          </li>
        </ul>
        <ul
          v-if="status.warnings.length"
          class="mt-1 list-disc pl-4 opacity-80"
        >
          <li
            v-for="message in status.warnings"
            :key="message"
          >
            警告：{{ message }}
          </li>
        </ul>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
