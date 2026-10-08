<script setup lang="ts">
/**
 * 「渲染 / 编辑」图标分段按钮（简报与笔记共用，放在标签行右侧）。agent 运行中编辑置灰，
 * 聚焦或悬停按钮所在位置说明原因（按钮禁用后自己收不到焦点，所以气泡挂在外面的包装元素上）。
 */
import { computed } from 'vue'
import { EyeIcon, PencilIcon } from '@lucide/vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const props = defineProps<{
  busy: boolean
  /** 要编辑的文件还不存在（或还在加载）：编辑按钮置灰并说明。 */
  unavailable?: boolean
}>()
const mode = defineModel<'view' | 'edit'>('mode', { required: true })

const base = 'flex size-6 items-center justify-center rounded disabled:opacity-50'
const active = 'bg-primary/10 text-primary'

/** 编辑为什么不可用；可用时为 `null`。 */
const editBlocker = computed(() => {
  if (props.busy) return 'agent 运行中，只读'
  if (props.unavailable) return '还没有这份文件，暂时不能编辑'
  return null
})
</script>

<template>
  <TooltipProvider :delay-duration="0">
    <div
      class="inline-flex items-center gap-0.5 rounded-md border p-0.5"
      role="group"
      aria-label="显示模式"
    >
      <Tooltip>
        <TooltipTrigger as-child>
          <button
            type="button"
            :class="[base, mode === 'view' ? active : 'hover:bg-muted']"
            data-testid="mode-view"
            aria-label="渲染"
            :aria-pressed="mode === 'view'"
            @click="mode = 'view'"
          >
            <EyeIcon class="size-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          渲染
        </TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger as-child>
          <span
            class="flex"
            data-testid="mode-edit-wrap"
            :tabindex="editBlocker ? 0 : undefined"
            :role="editBlocker ? 'button' : undefined"
            :aria-disabled="editBlocker ? 'true' : undefined"
            :aria-label="editBlocker ? `编辑（${editBlocker}）` : undefined"
          >
            <button
              type="button"
              :class="[base, mode === 'edit' ? active : 'hover:bg-muted']"
              data-testid="mode-edit"
              aria-label="编辑"
              :aria-pressed="mode === 'edit'"
              :disabled="editBlocker !== null"
              @click="mode = 'edit'"
            >
              <PencilIcon class="size-3.5" />
            </button>
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          {{ editBlocker ?? '编辑' }}
        </TooltipContent>
      </Tooltip>
    </div>
  </TooltipProvider>
</template>
