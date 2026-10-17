<script setup lang="ts">
/**
 * 通用文件画布（任务简报 T14，控制者裁定 1/2/3/4）：文件树 + CodeMirror
 * 编辑器。`FileTree`/`CodeEditor` 都是纯展示组件，这里负责：
 *
 * - 选中文件后拉内容（`useFileContentQuery`），二进制文件不拉：图片/音频/
 *   视频（`fileKind.mediaKind`）用 `<img>`/`<audio>`/`<video>` 直连原始文件
 *   端点预览（支持 Range），其余只显示占位（`fileKind.isTextFile`）。
 * - 只读判断：`busy`（父组件传入，来自当前会话的 turn 状态）或者
 *   `FileEntry.readonly`（`upstream/`）——见 `editorReadonly.ts`。
 * - 未保存修改的冲突：`composables/conflictState.ts` 状态机；`workspace_changed`
 *   让 `useFileContentQuery` 重新拉取，命中冲突时不覆盖，显示横幅。
 * - 保存：`useWriteFileMutation`（`PUT .../files/{path}?stage=`），403/409
 *   转成中文提示，不静默失败。
 * - 当前打开的文件从文件树消失（回滚/被删）：`missingFile.ts` 决定关闭
 *   编辑器还是保留只读内容（追加修复 G1，2026-09-28）。
 * - HTML（open-mode 设计 §7）：默认「预览」，用 `<iframe sandbox="allow-scripts">` 加载原始文件端点
 *   （不给同源，页面里的脚本拿不到应用的 cookie 与接口；相对路径按同一工作区解析）；「源码」就是编辑器。
 * - 「在 Finder 中打开」：后端在本机文件管理器里选中当前文件（没选中时打开工作区根目录）。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { useFileContentQuery, useFileTreeQuery, useWriteFileMutation } from '@/composables/queries'
import { ApiError } from '@/api/http'
import { revealInFileManager, workspaceFileUrl } from '@/api/endpoints'
import { FolderOpenIcon } from '@lucide/vue'
import CodeEditor from '@/components/CodeEditor.vue'
import FileTree from './FileTree.vue'
import { computeReadonly } from './editorReadonly'
import { edit, initBuffer, keepMine, loadLatest, saved, serverUpdate, type BufferState } from '@/composables/conflictState'
import { editorLanguage, isHtmlFile, isTextFile, mediaKind } from './fileKind'
import { computeMissingFileAction } from './missingFile'
import { fileManagerName } from './fileManagerName'

const props = defineProps<{
  projectId: string
  stage: string
  /** 当前项目是否有一轮正在跑（页面根据当前会话的 turn 状态算出）。 */
  busy: boolean
}>()

const { data: fileTree, dataUpdatedAt: treeUpdatedAt } = useFileTreeQuery(() => props.projectId)
const selectedPath = ref<string | null>(null)

const selectedEntry = computed(
  () => fileTree.value?.files.find((f) => f.path === selectedPath.value) ?? null,
)
const isTextSelected = computed(() => selectedPath.value !== null && isTextFile(selectedPath.value))
const selectedMedia = computed(() => (selectedPath.value ? mediaKind(selectedPath.value) : null))
const isHtmlSelected = computed(() => selectedPath.value !== null && isHtmlFile(selectedPath.value))
/** HTML 文件的视图：切换文件时回到预览，不持久化。 */
const htmlView = ref<'preview' | 'source'>('preview')
watch(selectedPath, () => {
  htmlView.value = 'preview'
})
const showHtmlPreview = computed(() => isHtmlSelected.value && htmlView.value === 'preview')

// 媒体地址带版本号，避免浏览器沿用旧内容：文件树每次因 `workspace_changed`
// 重新拉取都会更新 `dataUpdatedAt`。图片跟着刷新；音频/视频只在切换文件
// 时取一次版本号，不让 agent 写别的文件时打断正在播放的音频。
const mediaVersion = ref(0)
watch(
  [selectedPath, treeUpdatedAt],
  ([, updatedAt], [prevPath]) => {
    // Images and HTML previews follow every workspace change; audio/video only on file switch.
    const live = selectedMedia.value === 'image' || isHtmlSelected.value
    if (live || selectedPath.value !== prevPath) mediaVersion.value = updatedAt
  },
  { immediate: true },
)
const mediaUrl = computed(() =>
  selectedPath.value && (selectedMedia.value || isHtmlSelected.value)
    ? workspaceFileUrl(props.projectId, selectedPath.value, String(mediaVersion.value))
    : null,
)

// 文件树已加载、且选中的路径不在其中：文件被回滚/删除了（G1）。文件树
// 首次加载完成之前不判定，避免选中文件还没来得及被这次查询看到就被
// 误判为"消失"。
const fileMissing = computed(
  () =>
    selectedPath.value !== null &&
    fileTree.value !== undefined &&
    !fileTree.value.files.some((f) => f.path === selectedPath.value),
)

const { data: fileContent, isPending: contentPending } = useFileContentQuery(
  () => props.projectId,
  () => (isTextSelected.value && !fileMissing.value ? selectedPath.value : null),
)

const buffer = ref<BufferState | null>(null)

// 切换文件：重置缓冲区（等内容加载出来后在下面的 watch 里 initBuffer）。
watch(selectedPath, () => {
  buffer.value = null
})

// 内容查询有了新数据：首次加载直接采用；已经在编辑同一个文件时走冲突
// 状态机（`workspace_changed` 触发的重新拉取可能带来别人写的新内容）。
watch(fileContent, (content) => {
  if (content === undefined || !isTextSelected.value) return
  buffer.value = buffer.value === null ? initBuffer(content) : serverUpdate(buffer.value, content)
})

// 文件消失：干净就关闭编辑器；脏就保留内容只读展示，见 `missingFile.ts`。
watch(fileMissing, (missing) => {
  if (!missing) return
  const action = computeMissingFileAction({ fileMissing: missing, dirty: buffer.value?.dirty ?? false })
  if (action === 'close') {
    selectedPath.value = null
    buffer.value = null
  }
})

const currentLanguage = computed(() => editorLanguage(selectedPath.value ?? ''))

const readonlyDecision = computed(() =>
  computeReadonly({ busy: props.busy, isUpstream: selectedEntry.value?.readonly ?? false }),
)

const writeMutation = useWriteFileMutation(() => props.projectId)
const saveError = ref<string | null>(null)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return '保存失败：不在可写范围内'
    if (error.status === 409) return '保存失败：项目正在运行中的一轮，请稍后再试'
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

async function onSave(): Promise<void> {
  if (!buffer.value || !selectedPath.value) return
  saveError.value = null
  try {
    await writeMutation.mutateAsync({
      path: selectedPath.value,
      stage: props.stage,
      content: buffer.value.content,
    })
    buffer.value = saved(buffer.value, buffer.value.content)
  } catch (error) {
    saveError.value = describeError(error)
  }
}

const revealLabel = `在 ${fileManagerName()} 中打开`
const revealError = ref<string | null>(null)
watch(selectedPath, () => {
  revealError.value = null
})

async function onReveal(): Promise<void> {
  revealError.value = null
  try {
    await revealInFileManager(props.projectId, fileMissing.value ? '' : (selectedPath.value ?? ''))
  } catch (error) {
    revealError.value = describeError(error)
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
  <div class="grid min-h-0 flex-1 grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-3">
    <FileTree
      :files="fileTree?.files ?? []"
      :selected-path="selectedPath"
      @select="(path) => (selectedPath = path)"
    />

    <div class="flex min-h-0 flex-col gap-2">
      <div class="flex shrink-0 items-center gap-1">
        <p class="text-muted-foreground mr-auto truncate text-xs">
          {{ selectedPath && !fileMissing ? selectedPath : '' }}
        </p>
        <template v-if="isHtmlSelected && !fileMissing">
          <Button
            size="sm"
            :variant="htmlView === 'preview' ? 'secondary' : 'ghost'"
            class="h-7"
            data-testid="html-view-preview"
            @click="htmlView = 'preview'"
          >
            预览
          </Button>
          <Button
            size="sm"
            :variant="htmlView === 'source' ? 'secondary' : 'ghost'"
            class="h-7"
            data-testid="html-view-source"
            @click="htmlView = 'source'"
          >
            源码
          </Button>
        </template>
        <Button
          size="sm"
          variant="ghost"
          class="h-7"
          :title="selectedPath && !fileMissing ? revealLabel : `${revealLabel}（工作区目录）`"
          data-testid="reveal-in-file-manager"
          @click="onReveal"
        >
          <FolderOpenIcon class="size-3.5" />
          {{ revealLabel }}
        </Button>
      </div>
      <p
        v-if="revealError"
        class="text-destructive text-xs"
      >
        {{ revealError }}
      </p>
      <template v-if="!selectedPath">
        <p class="text-muted-foreground text-sm">
          从左侧选择一个文件
        </p>
      </template>
      <template v-else-if="fileMissing && buffer">
        <div class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm">
          该文件已不存在（可能被回滚或删除）。已保留你未保存的修改，只读展示——不会自动重新创建文件。
        </div>
        <CodeEditor
          :content="buffer.content"
          :language="currentLanguage"
          readonly
        />
      </template>
      <template v-else-if="showHtmlPreview && mediaUrl">
        <iframe
          :key="mediaUrl"
          :src="mediaUrl"
          :title="selectedPath ?? undefined"
          sandbox="allow-scripts"
          class="min-h-80 w-full flex-1 rounded border bg-white"
          data-testid="html-preview"
        />
      </template>
      <template v-else-if="selectedMedia && mediaUrl">
        <div class="bg-muted/40 flex min-h-0 flex-1 items-center justify-center overflow-auto rounded border p-3">
          <img
            v-if="selectedMedia === 'image'"
            :src="mediaUrl"
            :alt="selectedPath"
            class="max-h-full max-w-full object-contain"
          >
          <audio
            v-else-if="selectedMedia === 'audio'"
            :key="mediaUrl"
            :src="mediaUrl"
            controls
            preload="metadata"
            class="w-full"
          />
          <video
            v-else
            :key="mediaUrl"
            :src="mediaUrl"
            controls
            preload="metadata"
            class="max-h-full max-w-full"
          />
        </div>
      </template>
      <template v-else-if="!isTextSelected">
        <p class="text-muted-foreground text-sm">
          二进制文件，不可编辑：{{ selectedPath }}
        </p>
      </template>
      <template v-else-if="contentPending || !buffer">
        <p class="text-muted-foreground text-sm">
          加载中…
        </p>
      </template>
      <template v-else>
        <div
          v-if="buffer.conflict"
          class="border-destructive bg-destructive/10 flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm"
        >
          <span>这个文件在你编辑期间被更新了（可能是 agent 写的）。</span>
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
          v-if="readonlyDecision.readonly"
          class="text-muted-foreground text-xs"
        >
          {{ readonlyDecision.reason === 'busy' ? '只读：agent 正在运行' : '只读：upstream 只读产物' }}
        </p>

        <CodeEditor
          :content="buffer.content"
          :language="currentLanguage"
          :readonly="readonlyDecision.readonly"
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
            :disabled="!buffer.dirty || readonlyDecision.readonly || writeMutation.isPending.value"
            @click="onSave"
          >
            保存
          </Button>
        </div>
      </template>
    </div>
  </div>
</template>
