<script setup lang="ts">
/**
 * 回复操作栏（设计 §6）：复制、用量、用时、时间。数据来自 `TurnOut`；turn 缺失、还在运行或
 * 时间不合法时整行不显示。
 */
import { computed } from 'vue'
import { CheckIcon, ClockIcon, CopyIcon, DatabaseIcon } from '@lucide/vue'
import type { TurnOut } from '@/types/api'
import { formatTurnMeta } from '@/components/session/turnMeta'
import { useCopy } from './useCopy'

const props = defineProps<{
  turnId: string
  /** 这个 turn 最后一段助手文本：「复制」复制它。 */
  text: string
  turns: ReadonlyMap<string, TurnOut>
}>()

const meta = computed(() => formatTurnMeta(props.turns.get(props.turnId)))
const { copied, copy } = useCopy()
</script>

<template>
  <div
    v-if="meta"
    class="text-muted-foreground flex flex-wrap items-center gap-4 text-xs"
    data-testid="reply-footer"
  >
    <button
      type="button"
      class="hover:text-foreground"
      aria-label="复制回复"
      data-testid="reply-copy"
      @click="copy(text)"
    >
      <CheckIcon
        v-if="copied"
        class="size-4"
      />
      <CopyIcon
        v-else
        class="size-4"
      />
    </button>
    <span
      v-if="meta.tokens"
      class="flex items-center gap-1"
    ><DatabaseIcon class="size-4" />用量 {{ meta.tokenBreakdown ?? `${meta.tokens} tok` }}</span>
    <span
      v-if="meta.duration"
      class="flex items-center gap-1"
    ><ClockIcon class="size-4" />用时 {{ meta.duration }}</span>
    <span>{{ meta.time }}</span>
  </div>
</template>
