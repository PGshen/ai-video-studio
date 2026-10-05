<script setup lang="ts">
/** 手动渲染的结果：成功时是指标与分析图，失败时是错误列表（旧产物没有改动）。 */
import type { MusicRenderOut } from '@/types/api'
import { matchRows, metricRows } from './musicView'

defineProps<{ report: MusicRenderOut }>()
</script>

<template>
  <section
    class="flex flex-col gap-2 rounded border p-3 text-sm"
    :class="report.ok ? '' : 'border-destructive bg-destructive/10'"
    data-testid="render-report"
  >
    <template v-if="!report.ok">
      <p class="font-medium">
        渲染失败，配乐的旧产物没有改动
      </p>
      <ul
        class="list-disc pl-5"
        data-testid="render-errors"
      >
        <li
          v-for="(error, index) in report.errors"
          :key="index"
          class="break-words"
        >
          {{ error }}
        </li>
      </ul>
    </template>
    <template v-else>
      <p class="font-medium">
        渲染成功
      </p>
      <p class="text-muted-foreground text-xs">
        {{ report.retime_note }}
      </p>
      <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <template
          v-for="row in metricRows(report.metrics)"
          :key="row.label"
        >
          <dt class="text-muted-foreground">
            {{ row.label }}
          </dt>
          <dd class="tabular-nums">
            {{ row.value }}
          </dd>
        </template>
      </dl>
      <p
        v-if="matchRows(report.metrics).length > 0"
        class="text-xs"
        data-testid="render-matches"
      >
        事件匹配：
        <span
          v-for="row in matchRows(report.metrics)"
          :key="row.name"
          class="mr-2"
        >{{ row.name }} {{ row.matched }}/{{ row.detectable }}</span>
      </p>
      <ul
        v-if="report.warnings.length > 0"
        class="list-disc pl-5 text-xs"
        data-testid="render-warnings"
      >
        <li
          v-for="(warning, index) in report.warnings"
          :key="index"
        >
          {{ warning }}
        </li>
      </ul>
      <img
        v-if="report.picture_base64"
        :src="`data:${report.picture_media_type ?? 'image/jpeg'};base64,${report.picture_base64}`"
        alt="配乐分析图：波形、谱图、能量与起音"
        class="w-full rounded border"
        data-testid="render-picture"
      >
    </template>
  </section>
</template>
