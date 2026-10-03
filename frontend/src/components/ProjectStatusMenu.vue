<script setup lang="ts">
/**
 * 设置项目状态（进行中 / 已完成 / 已废弃）的下拉菜单。卡片上用紧凑的「⋯」按钮，
 * 项目信息里用带当前状态文字的按钮。状态只是项目上的标记，随时可以改回来。
 */
import { ChevronDown, Ellipsis } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useSetProjectStatusMutation } from '@/composables/queries'
import type { ProjectStatus } from '@/types/api'
import { STATUS_TEXT } from '@/composables/projectStatus'

const props = defineProps<{
  projectId: string
  status: ProjectStatus
  /** 紧凑模式：只显示「⋯」图标按钮（卡片右上角）。 */
  compact?: boolean
}>()

const OPTIONS: readonly ProjectStatus[] = ['active', 'completed', 'abandoned']
const mutation = useSetProjectStatusMutation()

function select(value: unknown): void {
  const status = value as ProjectStatus
  if (status === props.status || !OPTIONS.includes(status)) return
  mutation.mutate({ projectId: props.projectId, status })
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button
        v-if="compact"
        size="icon-xs"
        variant="ghost"
        title="设置项目状态"
        aria-label="设置项目状态"
        :data-testid="`project-status-menu-${projectId}`"
        :disabled="mutation.isPending.value"
      >
        <Ellipsis />
      </Button>
      <Button
        v-else
        size="xs"
        variant="outline"
        :data-testid="`project-status-menu-${projectId}`"
        :disabled="mutation.isPending.value"
      >
        {{ STATUS_TEXT[status] }}
        <ChevronDown />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      <DropdownMenuLabel>项目状态</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuRadioGroup
        :model-value="status"
        @update:model-value="select"
      >
        <DropdownMenuRadioItem
          v-for="option in OPTIONS"
          :key="option"
          :value="option"
          :data-testid="`project-status-${option}`"
        >
          {{ STATUS_TEXT[option] }}
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
