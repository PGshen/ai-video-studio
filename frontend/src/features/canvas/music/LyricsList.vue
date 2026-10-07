<script setup lang="ts">
/**
 * 歌词行列表（时间 + 文字）：当前播放位置所在的一句高亮，点击一行跳到这句的开始。只展示——
 * 歌词文件由上传区管理，画面怎么用歌词由 agent 决定。
 */
import { computed } from 'vue'
import type { LyricLineOut } from '@/types/api'
import { lyricAt } from './importView'
import { formatClock } from './musicView'

const props = defineProps<{ lines: readonly LyricLineOut[]; currentTime: number }>()
const emit = defineEmits<{ seek: [seconds: number] }>()

const current = computed(() => lyricAt(props.lines, props.currentTime))
</script>

<template>
  <section
    v-if="lines.length > 0"
    class="grid gap-1 text-sm"
    data-testid="lyrics-list"
  >
    <h3 class="text-muted-foreground text-xs">
      歌词（{{ lines.length }} 句）
    </h3>
    <ol class="max-h-72 overflow-y-auto">
      <li
        v-for="(line, index) in lines"
        :key="index"
        class="hover:bg-muted flex cursor-pointer gap-3 rounded px-2 py-0.5"
        :class="index === current ? 'bg-primary/10 font-medium' : ''"
        :aria-current="index === current ? 'true' : undefined"
        data-testid="lyric-row"
        @click="emit('seek', line.start)"
      >
        <span class="text-muted-foreground w-10 shrink-0 tabular-nums">{{ formatClock(line.start) }}</span>
        <span class="min-w-0 break-words">{{ line.text }}</span>
      </li>
    </ol>
  </section>
</template>
