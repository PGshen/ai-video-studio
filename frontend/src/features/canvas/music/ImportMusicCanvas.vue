<script setup lang="ts">
/**
 * 音乐 MV（导入音乐）的音乐画布（子项目 4B 设计 §4）：未上传时是上传区；已上传后左侧是播放器与能量
 * 曲线（叠加拍线、段落、截取区间，点击跳转），右侧是分析摘要与段落校验结果。只展示，不编辑
 * `sections.json`——修改交给 agent。定稿按钮等放在 `actions` 槽里。
 */
import { computed, ref } from 'vue'
import { musicAudioUrl } from '@/api/endpoints'
import { errorMessage } from '@/api/http'
import { useMusicMetaQuery } from '@/composables/queries'
import AnalysisSummary from './AnalysisSummary.vue'
import EnergyView from './EnergyView.vue'
import SourceUploader from './SourceUploader.vue'
import { formatClock } from './musicView'

const props = defineProps<{ projectId: string; busy: boolean }>()

const { data: meta, error: metaError } = useMusicMetaQuery(() => props.projectId)
const problem = computed(() =>
  metaError.value === null || metaError.value === undefined ? null : errorMessage(metaError.value),
)

const uploadedNote = ref(false)
const audio = ref<HTMLAudioElement | null>(null)
const currentTime = ref(0)
const src = computed(() => musicAudioUrl(props.projectId, meta.value?.hash))
const duration = computed(() => meta.value?.duration ?? 0)

function onTimeUpdate(): void {
  currentTime.value = audio.value?.currentTime ?? 0
}

function seek(seconds: number): void {
  const el = audio.value
  if (el) el.currentTime = seconds
  currentTime.value = seconds
}
defineExpose({ seek })
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-1 text-sm">
      <span class="font-medium">音乐</span>
      <div class="ml-auto flex items-center gap-2">
        <slot name="actions" />
      </div>
    </div>

    <p
      v-if="problem"
      class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm"
      role="alert"
      data-testid="music-problem"
    >
      {{ problem }}
    </p>

    <p
      v-if="uploadedNote"
      class="rounded border px-3 py-2 text-sm"
      role="status"
      data-testid="music-upload-note"
    >
      上传完成。让 agent 调用 analyze_music 分析这首歌。
    </p>

    <div
      v-if="meta && !meta.rendered"
      class="flex flex-col gap-2"
      data-testid="music-not-uploaded"
    >
      <SourceUploader
        :project-id="projectId"
        :busy="busy"
        :has-source="false"
        @uploaded="uploadedNote = true"
      />
    </div>

    <div
      v-else-if="meta"
      class="grid min-h-0 flex-1 content-start gap-4 overflow-y-auto lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"
      data-testid="music-import-body"
    >
      <div class="grid min-w-0 content-start gap-3">
        <audio
          ref="audio"
          :src="src"
          controls
          preload="metadata"
          class="w-full"
          data-testid="music-audio"
          @timeupdate="onTimeUpdate"
          @seeked="onTimeUpdate"
        />
        <EnergyView
          v-if="meta.energy && duration > 0"
          :energy="meta.energy"
          :grid="meta.grid"
          :range="meta.range"
          :sections="meta.sections"
          :duration="duration"
          :current-time="currentTime"
          @seek="seek"
        />
        <p
          v-else
          class="text-muted-foreground text-sm"
          data-testid="music-no-energy"
        >
          还没有能量曲线：让 agent 调用 analyze_music 分析这首歌。
        </p>
        <p
          v-if="duration > 0"
          class="text-muted-foreground text-xs tabular-nums"
        >
          {{ formatClock(currentTime) }} / {{ formatClock(duration) }}
        </p>
        <SourceUploader
          :project-id="projectId"
          :busy="busy"
          :has-source="true"
          @uploaded="uploadedNote = true"
        />
      </div>
      <AnalysisSummary :meta="meta" />
    </div>

    <p
      v-else-if="!problem"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
  </div>
</template>
