<script setup lang="ts">
/**
 * HTML 动画阶段（`animation_html`）的专属画布（子项目 2 设计 §7.2）：三个标签。
 *
 * - **镜头**：镜头列表来自 `html-preview/meta`（不依赖 `upstream/` 要等第一轮才物化），附
 *   "代码是否存在 / 检查状态"；代码用 `CodeEditor`（javascript）编辑，保存的阶段是
 *   `animation_html`。缓冲区状态机和 `AnimationCanvas.vue` 是同一套（`composables/conflictState.ts`
 *   `missingFile.ts`），各自复制一份而不共享：两个画布的镜头来源和文件后缀不同。
 * - **实时预览**：`HtmlPreviewPane`（沙盒 iframe 加传输控制）。
 * - **成片**：直接复用 `FinalRenderPanel`（读 job 进度，与引擎无关）；`v-show` 切换，渲染轮询不中断。
 *
 * `meta` 在 `workspace_changed` 之后重新取（`invalidateWorkspace`）；它不可用（叙事没定稿、配音
 * 没做完，409）时在每个标签里显示原因，不影响其余标签。
 */
import { computed, ref, watch, watchEffect } from 'vue'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/CodeEditor.vue'
import {
  useFileContentQuery,
  useFileTreeQuery,
  useHtmlPreviewMetaQuery,
  useSceneChecksQuery,
  useWriteFileMutation,
} from '@/composables/queries'
import { ApiError } from '@/api/http'
import {
  edit,
  initBuffer,
  keepMine,
  loadLatest,
  saved,
  serverUpdate,
  type BufferState,
} from '@/composables/conflictState'
import { computeMissingFileAction } from './missingFile'
import { computeSceneStatuses } from './sceneStatus'
import FinalRenderPanel from './FinalRenderPanel.vue'
import HtmlPreviewPane from './HtmlPreviewPane.vue'
import SceneList from './SceneList.vue'
import SceneReference, { type ReferenceTab } from './SceneReference.vue'
import { sceneInfoFromSection } from './htmlSceneInfo'

const props = defineProps<{
  projectId: string
  /** 当前项目是否有一轮正在跑；运行中编辑器只读。 */
  busy: boolean
}>()

const STAGE = 'animation_html'

const tab = ref<'scenes' | 'preview' | 'final'>('scenes')

const { data: meta, error: metaError } = useHtmlPreviewMetaQuery(() => props.projectId)
const sections = computed(() => meta.value?.sections ?? [])
const sceneIds = computed(() => sections.value.map((section) => section.id))

const metaProblem = computed<string | null>(() => {
  const error = metaError.value
  if (error === null || error === undefined) return null
  if (error instanceof ApiError) return typeof error.detail === 'string' ? error.detail : error.message
  return error instanceof Error ? error.message : String(error)
})

const { data: fileTree } = useFileTreeQuery(() => props.projectId)
const filePaths = computed(() => fileTree.value?.files.map((f) => f.path) ?? [])
const { data: sceneChecks } = useSceneChecksQuery(() => props.projectId, () => sceneIds.value)

const scenes = computed(() =>
  computeSceneStatuses(sceneIds.value, filePaths.value, sceneChecks.value?.scenes, 'js'),
)

// ---- 选中镜头 + 代码缓冲区 -----------------------------------------------------

const selectedSceneId = ref<string | null>(null)
const selectedScene = computed(() => scenes.value.find((s) => s.id === selectedSceneId.value) ?? null)
const selectedSection = computed(() => sections.value.find((s) => s.id === selectedSceneId.value) ?? null)
const sceneExists = computed(() => selectedScene.value?.exists ?? false)

const buffer = ref<BufferState | null>(null)
/** 这次选中期间是否真的从服务器加载到过内容（区分"从没写过"和"被回滚/删除了"）。 */
const hadContent = ref(false)

watch(selectedSceneId, () => {
  buffer.value = null
  hadContent.value = false
})

const { data: fileContent } = useFileContentQuery(
  () => props.projectId,
  () => (sceneExists.value ? (selectedScene.value?.path ?? null) : null),
)

// 同时盯着选中的镜头：查询缓存命中时 `fileContent` 一上来就有值（或和上一个镜头的内容相同），
// 只盯 `fileContent` 的话换镜头后不会有"变化"事件，缓冲区会一直是 `null`（"加载中…"）。
watch(
  [fileContent, selectedSceneId],
  ([content]) => {
    if (content === undefined) return
    hadContent.value = true
    buffer.value = buffer.value === null ? initBuffer(content) : serverUpdate(buffer.value, content)
  },
  { immediate: true },
)

watchEffect(() => {
  if (selectedSceneId.value === null) return
  if (sceneExists.value || hadContent.value) return
  if (buffer.value === null) buffer.value = initBuffer('')
})

const fileMissing = computed(
  () => selectedSceneId.value !== null && hadContent.value && !sceneExists.value,
)

watch(fileMissing, (missing) => {
  if (!missing) return
  const action = computeMissingFileAction({ fileMissing: missing, dirty: buffer.value?.dirty ?? false })
  if (action === 'close') {
    selectedSceneId.value = null
    buffer.value = null
    hadContent.value = false
  }
})

const referenceTab = ref<ReferenceTab>('preview')
const selectedPreview = computed(() => selectedScene.value?.renderPreview ?? null)
const selectedInfo = computed(() =>
  selectedSection.value === null ? null : sceneInfoFromSection(selectedSection.value),
)
const readonly = computed(() => props.busy)

const writeMutation = useWriteFileMutation(() => props.projectId)
const saveError = ref<string | null>(null)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return '保存失败：不在当前阶段的可写范围内'
    if (error.status === 409) return '保存失败：项目正在运行中的一轮，请稍后再试'
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

async function onSave(): Promise<void> {
  const path = selectedScene.value?.path
  if (!buffer.value || !path) return
  saveError.value = null
  try {
    await writeMutation.mutateAsync({ path, stage: STAGE, content: buffer.value.content })
    // 不在这里置 `hadContent`：文件树重新拉取之前会有一段"曾有内容但文件不存在"的窗口，
    // 会让 `fileMissing` 误判（同 `AnimationCanvas.vue` 的决策记录）。
    buffer.value = saved(buffer.value, buffer.value.content)
  } catch (error) {
    saveError.value = describeError(error)
  }
}

function onEdit(content: string): void {
  if (buffer.value) buffer.value = edit(buffer.value, content)
}
function onKeepMine(): void {
  if (buffer.value) buffer.value = keepMine(buffer.value)
}
function onLoadLatest(): void {
  if (buffer.value) buffer.value = loadLatest(buffer.value)
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div
      class="flex flex-wrap items-center gap-1 text-sm"
      data-testid="animation-tabbar"
    >
      <button
        type="button"
        class="rounded px-3 py-1 whitespace-nowrap"
        :class="tab === 'scenes' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        @click="tab = 'scenes'"
      >
        镜头（{{ scenes.length }}）
      </button>
      <button
        type="button"
        class="rounded px-3 py-1 whitespace-nowrap"
        :class="tab === 'preview' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        @click="tab = 'preview'"
      >
        实时预览
      </button>
      <button
        type="button"
        class="rounded px-3 py-1 whitespace-nowrap"
        :class="tab === 'final' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        @click="tab = 'final'"
      >
        成片
      </button>
      <div class="ml-auto flex items-center gap-2">
        <slot name="actions" />
      </div>
    </div>

    <p
      v-if="metaProblem"
      class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm"
      role="alert"
      data-testid="meta-problem"
    >
      时间轴不可用：{{ metaProblem }}
    </p>

    <div
      v-show="tab === 'scenes'"
      class="grid min-h-0 flex-1 grid-cols-[minmax(0,12rem)_minmax(0,1fr)] gap-3"
    >
      <SceneList
        :project-id="projectId"
        :scenes="scenes"
        :selected-id="selectedSceneId"
        @select="(id) => (selectedSceneId = id)"
      />

      <div class="flex min-h-0 flex-col gap-2">
        <template v-if="!selectedSceneId">
          <p class="text-muted-foreground text-sm">
            从左侧选择一个镜头
          </p>
        </template>
        <template v-else-if="fileMissing && buffer">
          <div class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm">
            该镜头的脚本已不存在（可能被回滚或删除）。已保留你未保存的修改，只读展示——不会自动重新创建文件。
          </div>
          <div class="min-h-0 flex-1">
            <CodeEditor
              :content="buffer.content"
              language="javascript"
              readonly
            />
          </div>
        </template>
        <template v-else-if="!buffer">
          <p class="text-muted-foreground text-sm">
            加载中…
          </p>
        </template>
        <template v-else>
          <SceneReference
            v-model:tab="referenceTab"
            :project-id="projectId"
            :scene-id="selectedSceneId"
            :images="selectedPreview?.images ?? []"
            :stale="selectedPreview?.stale ?? false"
            :narrative-scene="selectedInfo"
          />

          <div
            v-if="buffer.conflict"
            class="border-destructive bg-destructive/10 flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm"
          >
            <span>这个镜头的脚本在你编辑期间被更新了（可能是 agent 写的）。</span>
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

          <div class="min-h-0 flex-1">
            <CodeEditor
              :content="buffer.content"
              language="javascript"
              :readonly="readonly"
              @update:content="onEdit"
            />
          </div>

          <div class="flex items-center justify-between gap-2">
            <p
              v-if="saveError"
              class="text-destructive text-xs"
            >
              {{ saveError }}
            </p>
            <span
              v-else-if="readonly"
              class="text-muted-foreground text-xs"
            >
              只读：agent 正在运行
            </span>
            <span
              v-else-if="!sceneExists"
              class="text-muted-foreground truncate text-xs"
            >
              这个镜头还没有脚本，写完后保存即可创建 {{ selectedScene?.path }}
            </span>
            <span
              v-else-if="buffer.dirty"
              class="text-muted-foreground text-xs"
            >
              有未保存的修改
            </span>
            <span v-else />
            <Button
              size="sm"
              :disabled="!buffer.dirty || readonly || writeMutation.isPending.value"
              @click="onSave"
            >
              保存
            </Button>
          </div>
        </template>
      </div>
    </div>

    <template v-if="tab === 'preview'">
      <HtmlPreviewPane
        v-if="meta"
        :project-id="projectId"
        :meta="meta"
      />
      <p
        v-else-if="!metaProblem"
        class="text-muted-foreground text-sm"
      >
        加载中…
      </p>
    </template>

    <div
      v-show="tab === 'final'"
      class="min-h-0 flex-1 overflow-y-auto"
    >
      <FinalRenderPanel
        :project-id="projectId"
        :scene-count="scenes.length"
      />
    </div>
  </div>
</template>
