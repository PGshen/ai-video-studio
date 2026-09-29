<script setup lang="ts">
/**
 * 动画阶段画布（任务 T12）：镜头列表 + 代码编辑器 + 关键帧提示条。结构仿
 * `features/canvas/generic/FileCanvas.vue`（同一批 query/mutation、同一套
 * 缓冲区状态机——见 `conflictState.ts`/`missingFile.ts` 顶部注释，为什么是
 * 复制一份而不是直接 import），但换成 `SceneList.vue` 而不是通用
 * `FileTree.vue`：镜头列表来自 `upstream/narrative/narrative.json`（决策
 * 记录 D37：前端直接读通用文件端点自己解析，不新增"列出镜头"端点，后端
 * 目前也没有这样的端点）+ `animation/scenes/<id>.py` 是否存在（决策记录
 * D38：M2 只做这一个信号，不做"已校验/已过期"）。
 *
 * 镜头代码总是 `.py`，不需要像 `FileCanvas` 那样按扩展名判断语言/是否
 * 文本文件；也不需要 `upstream/` 只读判断——`animation/scenes/**` 一直是
 * 本阶段自己的可写范围，只读的原因只有"agent 正在跑一轮"（`props.busy`）
 * 一种。
 *
 * 镜头的"已校验/已过期"状态（TD-33）另外拉 `useSceneChecksQuery`（读模型，
 * 见 `api/scene_checks.py`），和文件是否存在这个信号（决策记录 D38）合并
 * 进同一个 `computeSceneStatuses` 调用。
 *
 * 任务 T13 加了 `FinalRenderPanel`（成片面板：渲染成片/进度/播放器/成片
 * 定稿），挂在镜头列表+编辑器这个 grid 下方，只在镜头列表已知（叙事已
 * 物化且解析无误）时显示——见该组件顶部注释。
 */
import { computed, ref, watch, watchEffect } from 'vue'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/CodeEditor.vue'
import type { EditorLanguage } from '@/components/codeEditorLanguage'
import {
  useFileContentQuery,
  useFileTreeQuery,
  useSceneChecksQuery,
  useWriteFileMutation,
} from '@/composables/queries'
import { ApiError } from '@/api/http'
import type { FileWriteResult } from '@/types/api'
import SceneList from './SceneList.vue'
import KeyframeStrip from './KeyframeStrip.vue'
import FinalRenderPanel from './FinalRenderPanel.vue'
import { NARRATIVE_JSON_PATH, parseNarrativeSceneIds } from './narrativeScenes'
import { computeSceneStatuses } from './sceneStatus'
import { edit, initBuffer, keepMine, loadLatest, saved, serverUpdate, type BufferState } from './conflictState'
import { computeMissingFileAction } from './missingFile'

const props = defineProps<{
  projectId: string
  /** 当前项目是否有一轮正在跑（同 `FileCanvas.vue` 的 `busy`）。 */
  busy: boolean
}>()

const SCENE_LANGUAGE: EditorLanguage = 'python'

// ---- 镜头列表：narrative.json 解析 + 代码文件是否存在 --------------------

const { data: fileTree } = useFileTreeQuery(() => props.projectId)

const filePaths = computed(() => fileTree.value?.files.map((f) => f.path) ?? [])
const narrativeMaterialized = computed(() => filePaths.value.includes(NARRATIVE_JSON_PATH))

const { data: narrativeContent } = useFileContentQuery(
  () => props.projectId,
  () => (narrativeMaterialized.value ? NARRATIVE_JSON_PATH : null),
)

const narrativeParse = computed<{ ids: string[]; error: string | null }>(() => {
  if (narrativeContent.value === undefined) return { ids: [], error: null }
  try {
    return { ids: parseNarrativeSceneIds(narrativeContent.value), error: null }
  } catch (error) {
    return { ids: [], error: error instanceof Error ? error.message : String(error) }
  }
})

const { data: sceneChecks } = useSceneChecksQuery(
  () => props.projectId,
  () => narrativeParse.value.ids,
)

const scenes = computed(() =>
  computeSceneStatuses(narrativeParse.value.ids, filePaths.value, sceneChecks.value?.scenes),
)

// ---- 选中镜头 + 代码编辑缓冲区 --------------------------------------------

const selectedSceneId = ref<string | null>(null)
const selectedScene = computed(
  () => scenes.value.find((s) => s.id === selectedSceneId.value) ?? null,
)
const sceneExists = computed(() => selectedScene.value?.exists ?? false)

const buffer = ref<BufferState | null>(null)
/** 当前选中的镜头本次是否已经从服务器真正加载到过内容——用来分辨"这个镜头
 * 从来没写过代码"（直接给一个空的可编辑缓冲区）和"曾经有代码，后来被回滚/
 * 删除了"（`missingFile.ts` 的"保留只读"分支）。 */
const hadContent = ref(false)

watch(selectedSceneId, () => {
  buffer.value = null
  hadContent.value = false
})

const { data: fileContent } = useFileContentQuery(
  () => props.projectId,
  () => (sceneExists.value ? selectedScene.value?.path ?? null : null),
)

watch(fileContent, (content) => {
  if (content === undefined) return
  hadContent.value = true
  buffer.value = buffer.value === null ? initBuffer(content) : serverUpdate(buffer.value, content)
})

// 选中的镜头还没有代码文件、且这次选中期间从没加载到过内容：给一个空的
// 可编辑缓冲区（新镜头，不是"消失的文件"）。只在 `buffer` 还是 `null` 时
// 设置一次，不会覆盖用户已经开始敲的内容。
watchEffect(() => {
  if (selectedSceneId.value === null) return
  if (sceneExists.value || hadContent.value) return
  if (buffer.value === null) buffer.value = initBuffer('')
})

// 曾经加载到内容、现在这个路径不存在了（回滚/被删）：见 missingFile.ts。
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
    const result: FileWriteResult = await writeMutation.mutateAsync({
      path,
      stage: 'animation',
      content: buffer.value.content,
    })
    buffer.value = saved(buffer.value, buffer.value.content)
    // 不在这里把 `hadContent` 设成 true（曾经这么写过，是一个真实 bug，见
    // 决策记录）：`useWriteFileMutation` 的 `onSuccess` 只是让文件树查询
    // 失效，真正的 `exists: true` 要等它重新拉取完才会反映到
    // `sceneExists`。如果保存后立刻把 `hadContent` 标成 true，会有一小段
    // `hadContent === true && sceneExists === false` 的窗口——`fileMissing`
    // 计算属性会在这段时间里误判成"曾经有内容、现在不存在了"，触发
    // `computeMissingFileAction` 把刚保存、缓冲区还是干净的编辑器直接关掉。
    // 交给下面 `fileContent` 查询在 `sceneExists` 真正变 `true` 后自然把
    // `hadContent` 置位，不会有这个竞态窗口。
    void result
  } catch (error) {
    saveError.value = describeError(error)
  }
}

function onEdit(content: string): void {
  if (!buffer.value) return
  buffer.value = edit(buffer.value, content)
}

function onKeepMine(): void {
  if (!buffer.value) return
  buffer.value = keepMine(buffer.value)
}

function onLoadLatest(): void {
  if (!buffer.value) return
  buffer.value = loadLatest(buffer.value)
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div class="grid min-h-0 flex-1 grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-3">
      <template v-if="!narrativeMaterialized">
        <p class="text-muted-foreground col-span-2 text-sm">
          还没有镜头列表：`upstream/narrative/` 要在这个会话跑过第一轮对话后才会物化。
          请先在左侧发一条消息开始一轮。
        </p>
      </template>
      <template v-else-if="narrativeParse.error">
        <p class="text-destructive col-span-2 text-sm">
          解析 narrative.json 失败：{{ narrativeParse.error }}
        </p>
      </template>
      <template v-else>
        <SceneList
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
              该镜头的代码文件已不存在（可能被回滚或删除）。已保留你未保存的修改，只读展示——不会自动重新创建文件。
            </div>
            <CodeEditor
              :content="buffer.content"
              :language="SCENE_LANGUAGE"
              readonly
            />
          </template>
          <template v-else-if="!buffer">
            <p class="text-muted-foreground text-sm">
              加载中…
            </p>
          </template>
          <template v-else>
            <div
              v-if="buffer.conflict"
              class="border-destructive bg-destructive/10 flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm"
            >
              <span>这个镜头的代码在你编辑期间被更新了（可能是 agent 写的）。</span>
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
              v-if="readonly"
              class="text-muted-foreground text-xs"
            >
              只读：agent 正在运行
            </p>
            <p
              v-else-if="!sceneExists"
              class="text-muted-foreground text-xs"
            >
              这个镜头还没有代码，写完后保存即可创建 {{ selectedScene?.path }}
            </p>

            <CodeEditor
              :content="buffer.content"
              :language="SCENE_LANGUAGE"
              :readonly="readonly"
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

            <KeyframeStrip :scene-id="selectedSceneId" />
          </template>
        </div>
      </template>
    </div>

    <FinalRenderPanel
      v-if="narrativeMaterialized && !narrativeParse.error"
      :project-id="projectId"
      :scene-count="scenes.length"
    />
  </div>
</template>
