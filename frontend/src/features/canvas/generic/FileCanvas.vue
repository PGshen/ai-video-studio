<script setup lang="ts">
/**
 * 通用文件画布（任务简报 T14，控制者裁定 1/2/3/4）：文件树 + CodeMirror
 * 编辑器。`FileTree`/`CodeEditor` 都是纯展示组件，这里负责：
 *
 * - 选中文件后拉内容（`useFileContentQuery`），二进制文件不拉，只显示
 *   占位（`fileKind.isTextFile`）。
 * - 只读判断：`busy`（父组件传入，来自当前会话的 turn 状态）或者
 *   `FileEntry.readonly`（`upstream/`）——见 `editorReadonly.ts`。
 * - 未保存修改的冲突：`conflictState.ts` 状态机；`workspace_changed`
 *   让 `useFileContentQuery` 重新拉取，命中冲突时不覆盖，显示横幅。
 * - 保存：`useWriteFileMutation`（`PUT .../files/{path}?stage=`），403/409
 *   转成中文提示，不静默失败。
 */
import { computed, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { useFileContentQuery, useFileTreeQuery, useWriteFileMutation } from '@/composables/queries'
import { ApiError } from '@/api/http'
import FileTree from './FileTree.vue'
import CodeEditor from './CodeEditor.vue'
import { computeReadonly } from './editorReadonly'
import { edit, initBuffer, keepMine, loadLatest, saved, serverUpdate, type BufferState } from './conflictState'
import { editorLanguage, isTextFile } from './fileKind'

const props = defineProps<{
  projectId: string
  stage: string
  /** 当前项目是否有一轮正在跑（页面根据当前会话的 turn 状态算出）。 */
  busy: boolean
}>()

const { data: fileTree } = useFileTreeQuery(() => props.projectId)
const selectedPath = ref<string | null>(null)

const selectedEntry = computed(
  () => fileTree.value?.files.find((f) => f.path === selectedPath.value) ?? null,
)
const isTextSelected = computed(() => selectedPath.value !== null && isTextFile(selectedPath.value))

const { data: fileContent, isPending: contentPending } = useFileContentQuery(
  () => props.projectId,
  () => (isTextSelected.value ? selectedPath.value : null),
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

const currentLanguage = computed(() => editorLanguage(selectedPath.value ?? ''))

const readonlyDecision = computed(() =>
  computeReadonly({ busy: props.busy, isUpstream: selectedEntry.value?.readonly ?? false }),
)

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
      <template v-if="!selectedPath">
        <p class="text-muted-foreground text-sm">
          从左侧选择一个文件
        </p>
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
