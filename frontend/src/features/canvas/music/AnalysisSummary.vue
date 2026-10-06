<script setup lang="ts">
/**
 * 歌曲（MV）的右栏：源文件、分析摘要（BPM、置信度、拟合残差、时长、警告），以及"源文件已更换"的
 * 醒目提示。分析的 BPM 与网格只是参考：怎么用交给 agent。只展示。
 */
import { computed } from 'vue'
import type { MusicMetaOut } from '@/types/api'
import { analysisRows } from './importView'

const props = defineProps<{ meta: MusicMetaOut }>()

const rows = computed(() => analysisRows(props.meta))

function megabytes(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div
    class="grid content-start gap-3 text-sm"
    data-testid="music-analysis"
  >
    <p
      v-if="meta.stale"
      class="rounded border border-amber-500 bg-amber-500/10 px-3 py-2"
      role="status"
      data-testid="music-stale"
    >
      源文件已更换，现有分析对应的是另一首歌。请让 agent 重新分析（analyze_music）。
    </p>

    <p
      v-if="meta.source"
      class="text-muted-foreground text-xs"
      data-testid="music-source-info"
    >
      {{ meta.source.filename }} · {{ megabytes(meta.source.size) }}
    </p>

    <dl
      v-if="rows.length > 0 && !meta.stale"
      class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1"
      data-testid="music-analysis-rows"
    >
      <template
        v-for="row in rows"
        :key="row.label"
      >
        <dt class="text-muted-foreground">
          {{ row.label }}
        </dt>
        <dd
          class="tabular-nums"
          :class="row.attention ? 'font-medium text-amber-600' : ''"
          data-testid="music-analysis-row"
          :data-attention="String(row.attention)"
        >
          {{ row.value }}
        </dd>
      </template>
    </dl>
    <p
      v-else-if="!meta.stale"
      class="text-muted-foreground"
      data-testid="music-analysis-empty"
    >
      还没有分析。让 agent 调用 analyze_music 分析这首歌。
    </p>
  </div>
</template>
