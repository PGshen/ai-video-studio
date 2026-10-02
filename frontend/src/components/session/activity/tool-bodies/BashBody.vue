<script setup lang="ts">
/**
 * `bash`：终端风格——状态点 + 命令（`shell` 的 `commands` 逐条列出）+ 输出。失败的命令输出
 * 本身就是结果，所以这里自己显示（红色），不再叠加通用的错误面板。
 */
import { computed } from 'vue'
import { LoaderCircleIcon } from '@lucide/vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import type { ToolStatus } from '@/components/session/toolPresentation'
import ToolPane from '@/components/session/activity/ToolPane.vue'

const props = defineProps<{ item: ToolCallItem; status: ToolStatus }>()

const commands = computed(() => {
  const { command, commands: list } = props.item.args
  if (typeof command === 'string' && command.trim() !== '') return [command]
  return Array.isArray(list) ? list.filter((c): c is string => typeof c === 'string') : []
})
const output = computed(() => props.item.result?.text ?? '')
const copyText = computed(() =>
  [...commands.value.map((c) => `$ ${c}`), output.value].filter((part) => part !== '').join('\n'),
)
const DOT: Record<ToolStatus, string> = {
  running: '',
  done: 'bg-green-500',
  error: 'bg-red-500',
  interrupted: 'bg-muted-foreground',
}
</script>

<template>
  <ToolPane :copy-text="copyText">
    <template #title>
      <LoaderCircleIcon
        v-if="status === 'running'"
        class="size-3 animate-spin"
        data-testid="bash-status"
        data-status="running"
      />
      <span
        v-else
        class="inline-block size-2 rounded-full"
        :class="DOT[status]"
        data-testid="bash-status"
        :data-status="status"
      />
      <span>终端</span>
    </template>
    <div class="p-3 font-mono">
      <div
        v-for="(command, index) in commands"
        :key="index"
        data-testid="bash-command"
        class="whitespace-pre-wrap"
      >
        $ {{ command }}
      </div>
      <pre
        v-if="output !== ''"
        class="mt-2 whitespace-pre-wrap"
        :class="item.result?.isError ? 'text-destructive' : ''"
      >{{ output }}</pre>
      <p
        v-else-if="item.result"
        class="text-muted-foreground mt-2"
      >
        （无输出）
      </p>
    </div>
  </ToolPane>
</template>
