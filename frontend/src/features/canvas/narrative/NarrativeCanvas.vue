<script setup lang="ts">
/**
 * 叙事阶段画布（M3 T10）：镜头卡片列表 + 选中镜头的详情（旁白、beats、
 * 校验问题、配音播放条）+ 原始 JSON 标签页。整体结构仿
 * `features/canvas/animation/AnimationCanvas.vue`：状态都从通用文件端点读
 * （`narrative/narrative.json`、`narrative/timing.json`），不新增后端接口。
 *
 * - 校验标记和"是否已配音"由 `narrativeDoc.ts`/`timingStatus.ts` 在前端
 *   算（校验的权威来源仍是后端 `validate_narrative`，见 narrativeDoc.ts）。
 * - 顶部状态条给出定稿前提（校验通过、全部配音、对齐覆盖率达标）的当前
 *   满足情况；这只是提示，后端 `finalize` 不强制这些条件（设计 §5.2 的
 *   定稿条件由用户确认）。
 * - JSON 标签页可编辑：缓冲区/冲突处理是 `animation/conflictState.ts` 那套
 *   逻辑的简化内联版（features 之间不能互相 import，那份状态机也不值得
 *   为了这一处再复制成独立模块）——缓冲区干净时直接采用服务器新内容，脏时
 *   进入冲突态让用户选择。agent 运行时（`busy`）画布只读。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/CodeEditor.vue'
import { ApiError } from '@/api/http'
import { workspaceFileUrl } from '@/api/endpoints'
import {
  useFileContentQuery,
  useFileTreeQuery,
  useProjectQuery,
  useWriteFileMutation,
} from '@/composables/queries'
import BeatTimeline from './BeatTimeline.vue'
import SceneCardList from './SceneCardList.vue'
import {
  NARRATIVE_PATH,
  duplicateSceneIds,
  parseNarrativeDoc,
  sceneIssues,
  type NarrativeScene,
} from './narrativeDoc'
import {
  TIMING_PATH,
  computeDubbing,
  computeReadiness,
  overallCoverage,
  type CurrentDubbingInputs,
  type SceneDubbing,
} from './timingStatus'

const props = defineProps<{
  projectId: string
  /** 当前项目是否有一轮正在跑（同 `FileCanvas.vue` 的 `busy`）。 */
  busy: boolean
}>()

type Tab = 'scenes' | 'json'
const tab = ref<Tab>('scenes')

// ---- 读文件 ----------------------------------------------------------------

const { data: fileTree } = useFileTreeQuery(() => props.projectId)
const filePaths = computed(() => new Set(fileTree.value?.files.map((f) => f.path) ?? []))
const narrativeExists = computed(() => filePaths.value.has(NARRATIVE_PATH))
const timingExists = computed(() => filePaths.value.has(TIMING_PATH))

const { data: narrativeContent } = useFileContentQuery(
  () => props.projectId,
  () => (narrativeExists.value ? NARRATIVE_PATH : null),
)
const { data: timingContent } = useFileContentQuery(
  () => props.projectId,
  () => (timingExists.value ? TIMING_PATH : null),
)

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

const narrativeParse = computed<{ scenes: NarrativeScene[]; error: string | null }>(() => {
  if (narrativeContent.value === undefined) return { scenes: [], error: null }
  try {
    return { scenes: parseNarrativeDoc(narrativeContent.value), error: null }
  } catch (error) {
    return { scenes: [], error: errorMessage(error) }
  }
})
const scenes = computed(() => narrativeParse.value.scenes)
const sceneIds = computed(() => scenes.value.map((s) => s.id))

const issuesById = computed<Record<string, string[]>>(() => {
  const duplicated = new Set(duplicateSceneIds(scenes.value))
  const result: Record<string, string[]> = {}
  for (const scene of scenes.value) {
    const issues = sceneIssues(scene)
    if (duplicated.has(scene.id)) issues.push('镜头 id 重复')
    result[scene.id] = issues
  }
  return result
})
const issueSceneCount = computed(
  () => Object.values(issuesById.value).filter((issues) => issues.length > 0).length,
)

// 与后端 `synthesize_tts` 的默认值一致（项目设置里没有 voice/speech_rate 时）。
const DEFAULT_VOICE = 'zizi'
const DEFAULT_SPEED = 1

const { data: project } = useProjectQuery(() => props.projectId)
// 项目还没加载出来时不判"配音已过期"，避免闪一下误报。
const currentInputs = computed<CurrentDubbingInputs | undefined>(() => {
  if (project.value === undefined) return undefined
  const settings = project.value.settings
  const voice = settings.voice
  const speed = settings.speech_rate
  return {
    narrations: Object.fromEntries(scenes.value.map((s) => [s.id, s.narration])),
    voice: typeof voice === 'string' ? voice : DEFAULT_VOICE,
    speed: typeof speed === 'number' ? speed : DEFAULT_SPEED,
  }
})

const timingParse = computed<{ dubbing: SceneDubbing[]; error: string | null }>(() => {
  if (timingExists.value && timingContent.value === undefined) {
    return { dubbing: computeDubbing(sceneIds.value, null), error: null }
  }
  try {
    return {
      dubbing: computeDubbing(
        sceneIds.value,
        timingExists.value ? timingContent.value! : null,
        currentInputs.value,
      ),
      error: null,
    }
  } catch (error) {
    return { dubbing: computeDubbing(sceneIds.value, null), error: errorMessage(error) }
  }
})
const dubbingById = computed<Record<string, SceneDubbing>>(() =>
  Object.fromEntries(timingParse.value.dubbing.map((d) => [d.id, d])),
)

const readiness = computed(() =>
  computeReadiness({
    sceneCount: scenes.value.length,
    issueSceneCount: issueSceneCount.value,
    dubbing: timingParse.value.dubbing,
  }),
)
const coverageLabel = computed(() => {
  const coverage = overallCoverage(timingParse.value.dubbing)
  return coverage === null ? null : `${Math.round(coverage * 100)}%`
})

// ---- 选中镜头 --------------------------------------------------------------

const selectedId = ref<string | null>(null)
const selectedScene = computed(() => scenes.value.find((s) => s.id === selectedId.value) ?? null)
const selectedTiming = computed(() =>
  selectedId.value === null ? null : (dubbingById.value[selectedId.value]?.timing ?? null),
)
const selectedAudioUrl = computed(() => {
  const timing = selectedTiming.value
  if (timing === null || !filePaths.value.has(timing.audio_path)) return null
  return workspaceFileUrl(props.projectId, timing.audio_path, timing.audio_hash)
})

watch(scenes, (list) => {
  if (selectedId.value !== null && !list.some((s) => s.id === selectedId.value)) {
    selectedId.value = null
  }
})

// ---- JSON 标签页的编辑缓冲区 -----------------------------------------------

interface Buffer {
  content: string
  saved: string
  incoming: string | null
}
const buffer = ref<Buffer | null>(null)
const dirty = computed(() => buffer.value !== null && buffer.value.content !== buffer.value.saved)
const conflict = computed(() => buffer.value?.incoming != null)

watch(narrativeContent, (content) => {
  if (content === undefined) return
  const current = buffer.value
  if (current === null || (current.content === current.saved && current.incoming === null)) {
    buffer.value = { content, saved: content, incoming: null }
  } else if (content !== current.saved) {
    buffer.value = { ...current, incoming: content }
  }
})
watch(narrativeExists, (exists) => {
  if (!exists) buffer.value = null
})

function onEdit(content: string): void {
  if (buffer.value) buffer.value = { ...buffer.value, content }
}
function onKeepMine(): void {
  if (buffer.value?.incoming != null) {
    buffer.value = { ...buffer.value, saved: buffer.value.incoming, incoming: null }
  }
}
function onLoadLatest(): void {
  if (buffer.value?.incoming != null) {
    const latest = buffer.value.incoming
    buffer.value = { content: latest, saved: latest, incoming: null }
  }
}

const writeMutation = useWriteFileMutation(() => props.projectId)
const saveError = ref<string | null>(null)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return '保存失败：不在当前阶段的可写范围内'
    if (error.status === 409) return '保存失败：项目正在运行中的一轮，请稍后再试'
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return errorMessage(error)
}

async function onSave(): Promise<void> {
  if (!buffer.value) return
  saveError.value = null
  const content = buffer.value.content
  try {
    await writeMutation.mutateAsync({ path: NARRATIVE_PATH, stage: 'narrative', content })
    buffer.value = { content, saved: content, incoming: null }
  } catch (error) {
    saveError.value = describeError(error)
  }
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <p
      v-if="fileTree !== undefined && !narrativeExists"
      class="text-muted-foreground text-sm"
    >
      还没有 narrative/narrative.json。在左侧和 agent 对话，让它写出第一版叙事。
    </p>
    <p
      v-else-if="narrativeParse.error"
      class="text-destructive text-sm"
    >
      解析 narrative.json 失败：{{ narrativeParse.error }}
    </p>
    <template v-else-if="narrativeExists">
      <div
        class="rounded border px-3 py-2 text-sm"
        :class="readiness.ready ? 'border-emerald-300 bg-emerald-50 text-emerald-900' : 'bg-muted'"
        data-testid="readiness"
      >
        <template v-if="readiness.ready">
          可以定稿：{{ scenes.length }} 个镜头全部校验通过并已配音，对齐覆盖率 {{ coverageLabel }}。
        </template>
        <template v-else>
          暂不满足定稿条件：{{ readiness.reasons.join('；') }}
          <template v-if="coverageLabel">
            （当前对齐覆盖率 {{ coverageLabel }}）
          </template>
        </template>
        <p
          v-if="timingParse.error"
          class="text-destructive mt-1 text-xs"
        >
          解析 timing.json 失败：{{ timingParse.error }}
        </p>
      </div>

      <div class="flex gap-1 text-sm">
        <button
          type="button"
          class="rounded px-3 py-1"
          :class="tab === 'scenes' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
          @click="tab = 'scenes'"
        >
          镜头
        </button>
        <button
          type="button"
          class="rounded px-3 py-1"
          :class="tab === 'json' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
          @click="tab = 'json'"
        >
          原始 JSON
        </button>
      </div>

      <div
        v-if="tab === 'scenes'"
        class="grid min-h-0 flex-1 grid-cols-[minmax(0,16rem)_minmax(0,1fr)] gap-3"
      >
        <SceneCardList
          :scenes="scenes"
          :issues="issuesById"
          :dubbing="dubbingById"
          :selected-id="selectedId"
          @select="(id) => (selectedId = id)"
        />

        <div class="flex min-h-0 flex-col gap-3 overflow-y-auto text-sm">
          <p
            v-if="!selectedScene"
            class="text-muted-foreground"
          >
            从左侧选择一个镜头
          </p>
          <template v-else>
            <section>
              <h3 class="text-muted-foreground mb-1 text-xs font-medium">
                旁白
              </h3>
              <p>{{ selectedScene.narration || '（空）' }}</p>
              <h3 class="text-muted-foreground mt-2 mb-1 text-xs font-medium">
                画面意图
              </h3>
              <p>{{ selectedScene.visual_intent || '（空）' }}</p>
            </section>

            <ul
              v-if="(issuesById[selectedScene.id] ?? []).length > 0"
              class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-xs"
              data-testid="scene-issues"
            >
              <li
                v-for="issue in issuesById[selectedScene.id]"
                :key="issue"
              >
                {{ issue }}
              </li>
            </ul>

            <section>
              <h3 class="text-muted-foreground mb-1 text-xs font-medium">
                配音
              </h3>
              <BeatTimeline
                v-if="selectedTiming && selectedAudioUrl"
                :audio-url="selectedAudioUrl"
                :duration-seconds="selectedTiming.duration_seconds"
                :timings="selectedTiming.beats"
                :beats="selectedScene.beats"
              />
              <p
                v-else-if="selectedTiming"
                class="text-muted-foreground text-xs"
              >
                timing.json 里有这个镜头，但找不到音频文件 {{ selectedTiming.audio_path }}。
              </p>
              <p
                v-else
                class="text-muted-foreground text-xs"
              >
                这个镜头还没有配音——让 agent 调用 synthesize_tts。
              </p>
              <p
                v-if="selectedTiming"
                class="text-muted-foreground mt-1 text-xs"
              >
                对齐覆盖率 {{ Math.round(selectedTiming.alignment_coverage * 100) }}%
              </p>
            </section>

            <section>
              <h3 class="text-muted-foreground mb-1 text-xs font-medium">
                Beats
              </h3>
              <ol class="flex flex-col gap-2">
                <li
                  v-for="(beat, index) in selectedScene.beats"
                  :key="index"
                  class="rounded border px-3 py-2"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-medium">{{ index + 1 }}. {{ beat.cue_text }}</span>
                    <span class="bg-muted shrink-0 rounded px-1.5 py-0.5 text-xs">
                      {{ beat.transition || '（无）' }}
                    </span>
                  </div>
                  <p class="text-muted-foreground mt-1 text-xs">
                    画面：{{ beat.visual_action }}
                  </p>
                  <p class="text-muted-foreground text-xs">
                    重点：{{ beat.emphasis }}
                  </p>
                </li>
              </ol>
            </section>
          </template>
        </div>
      </div>

      <div
        v-else
        class="flex min-h-0 flex-1 flex-col gap-2"
      >
        <template v-if="!buffer">
          <p class="text-muted-foreground text-sm">
            加载中…
          </p>
        </template>
        <template v-else>
          <div
            v-if="conflict"
            class="border-destructive bg-destructive/10 flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm"
          >
            <span>narrative.json 在你编辑期间被更新了（可能是 agent 写的）。</span>
            <div class="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                @click="onKeepMine"
              >
                保留我的修改
              </Button>
              <Button
                size="sm"
                variant="outline"
                @click="onLoadLatest"
              >
                载入最新
              </Button>
            </div>
          </div>
          <p
            v-if="busy"
            class="text-muted-foreground text-xs"
          >
            只读：agent 正在运行
          </p>
          <CodeEditor
            :content="buffer.content"
            language="json"
            :readonly="busy"
            @update:content="onEdit"
          />
          <div class="flex items-center justify-between">
            <p
              v-if="saveError"
              class="text-destructive text-xs"
            >
              {{ saveError }}
            </p>
            <span
              v-else-if="dirty"
              class="text-muted-foreground text-xs"
            >
              有未保存的修改
            </span>
            <span v-else />
            <Button
              size="sm"
              :disabled="!dirty || busy || writeMutation.isPending.value"
              @click="onSave"
            >
              保存
            </Button>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>
