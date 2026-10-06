<script setup lang="ts">
/**
 * 音乐 MV（歌曲）的音乐画布（子项目 4B 设计 §4，produce 设计 §9）：未上传时是上传区（只在「创意与要求」
 * 阶段）；已上传后左侧是播放器与能量曲线（叠加分析的参考拍线、镜头划分、截取区间，点击跳转）与歌词上传，
 * 右侧是分析摘要与歌词列表（点击跳转）。只展示——镜头划分、截取区间都由 agent 写。定稿按钮等放在 `actions` 槽里。
 */
import { computed, ref } from 'vue'
import { musicAudioUrl } from '@/api/endpoints'
import { errorMessage } from '@/api/http'
import { useMusicMetaQuery } from '@/composables/queries'
import AnalysisSummary from './AnalysisSummary.vue'
import EnergyView from './EnergyView.vue'
import LyricsList from './LyricsList.vue'
import LyricsUploader from './LyricsUploader.vue'
import SourceUploader from './SourceUploader.vue'
import { formatClock } from './musicView'

const props = withDefaults(
  defineProps<{
    projectId: string
    busy: boolean
    /** 显示上传区。歌曲在「创意与要求」阶段上传；「配乐与动画」里只看分析，不换歌。 */
    allowUpload?: boolean
    /** 嵌在别的画布里时不显示自己的标题行。 */
    compact?: boolean
  }>(),
  { allowUpload: true, compact: false },
)

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
    <div
      v-if="!compact"
      class="flex flex-wrap items-center gap-1 text-sm"
    >
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
        v-if="allowUpload"
        :project-id="projectId"
        :busy="busy"
        :has-source="false"
        @uploaded="uploadedNote = true"
      />
      <p
        v-else
        class="text-muted-foreground text-sm"
        data-testid="music-upload-elsewhere"
      >
        还没有上传歌曲。在「创意与要求」阶段（进行中）上传，上传后让 agent 分析；已定稿的话先重新打开该阶段。
      </p>
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
          v-if="allowUpload"
          :project-id="projectId"
          :busy="busy"
          :has-source="true"
          @uploaded="uploadedNote = true"
        />
        <LyricsUploader
          v-if="allowUpload"
          :project-id="projectId"
          :busy="busy"
          :lines="meta.lyrics.length"
        />
      </div>
      <div class="grid min-w-0 content-start gap-4">
        <AnalysisSummary :meta="meta" />
        <LyricsList
          :lines="meta.lyrics"
          :current-time="currentTime"
          @seek="seek"
        />
      </div>
    </div>

    <p
      v-else-if="!problem"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
  </div>
</template>
