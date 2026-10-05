<script setup lang="ts">
/**
 * 导入音乐的右栏：源文件、分析摘要（BPM、置信度、拟合残差、时长、警告）、`sections.json` 的校验结果，
 * 以及"源文件已更换"的醒目提示。只展示：修改段落交给 agent。
 */
import { computed } from 'vue'
import type { MusicMetaOut } from '@/types/api'
import { analysisRows } from './importView'

const props = defineProps<{ meta: MusicMetaOut }>()

const rows = computed(() => analysisRows(props.meta))
const check = computed(() => props.meta.sections_check)

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
      源文件已更换，现有分析与段落对应的是另一首歌。请让 agent 重新分析（analyze_music）。
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

    <div
      v-if="check && !meta.stale"
      data-testid="music-check"
    >
      <p
        v-if="check.ok"
        class="text-xs"
        data-testid="music-check-ok"
      >
        段落校验通过
      </p>
      <template v-else>
        <p class="text-xs font-medium">
          段落校验没有通过
        </p>
        <ul class="list-disc pl-5 text-xs">
          <li
            v-for="(error, index) in check.errors"
            :key="index"
            class="text-destructive"
            data-testid="music-check-error"
          >
            {{ error }}
          </li>
        </ul>
      </template>
      <ul
        v-if="check.warnings.length > 0"
        class="list-disc pl-5 text-xs"
      >
        <li
          v-for="(warning, index) in check.warnings"
          :key="index"
          data-testid="music-check-warning"
        >
          {{ warning }}
        </li>
      </ul>
    </div>
  </div>
</template>
