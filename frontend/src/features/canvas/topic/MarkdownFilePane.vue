<script setup lang="ts">
/**
 * 一个 Markdown 文件的渲染视图 + 编辑模式（计划 M4 T11）：选题简报和调研笔记共用。
 *
 * 缓冲区/冲突处理用共享的 `composables/conflictState.ts`：缓冲区干净时直接采用服务器的新内容
 * （agent 写的），脏时进入冲突态让用户选择；`path` 变化时重置。agent 运行时（`busy`）只读，不能切到编辑或保存。渲染视图显示的是缓冲区内容，
 * 所以编辑后不保存也能看到渲染效果。渲染/编辑的切换按钮在父组件的标签行里，`mode` 用 `v-model:mode` 同步；
 * 这里只负责在换文件、文件被删、agent 开始运行时把它退回渲染。
 */
import { computed, ref, watch } from 'vue'
import { ApiError } from '@/api/http'
import CodeEditor from '@/components/CodeEditor.vue'
import MessageResponse from '@/components/ai-elements/message/MessageResponse.vue'
import { Button } from '@/components/ui/button'
import {
  edit,
  initBuffer,
  keepMine,
  loadLatest,
  saved,
  serverUpdate,
  type BufferState,
} from '@/composables/conflictState'
import {
  useFileContentQuery,
  useFileTreeQuery,
  useWriteFileMutation,
} from '@/composables/queries'

const props = defineProps<{
  projectId: string
  /** 工作区相对路径，例如 `topic/brief.md`。 */
  path: string
  stage: string
  busy: boolean
  /** 文件不存在时显示的提示。 */
  emptyHint: string
}>()

const mode = defineModel<'view' | 'edit'>('mode', { default: 'view' })
const buffer = ref<BufferState | null>(null)
const saveError = ref<string | null>(null)

// 文件是否存在看文件树，不靠读取 404（TanStack 会对失败的请求重试，"加载中"会拖很久）。
const { data: fileTree } = useFileTreeQuery(() => props.projectId)
const exists = computed(() => fileTree.value?.files.some((f) => f.path === props.path))
const { data: fileContent, isError } = useFileContentQuery(
  () => props.projectId,
  () => (exists.value ? props.path : null),
)

watch(
  () => [props.path, fileContent.value] as const,
  ([path, content], previous) => {
    if (previous === undefined || path !== previous[0]) {
      buffer.value = null
      saveError.value = null
      mode.value = 'view'
    }
    if (content === undefined) return
    buffer.value = buffer.value === null ? initBuffer(content) : serverUpdate(buffer.value, content)
  },
  { immediate: true },
)

// agent 开始运行时退出编辑模式（编辑器本来也是只读的，回到渲染视图更清楚）。
watch(
  () => props.busy,
  (busy) => {
    if (busy) mode.value = 'view'
  },
)

const missing = computed(() => fileTree.value !== undefined && !exists.value)

// 文件被回滚/删除：清空缓冲区（不会在 agent 已经不再有的文件上保留编辑状态）。
watch(exists, (now) => {
  if (now === false) {
    buffer.value = null
    mode.value = 'view'
  }
})

const writeMutation = useWriteFileMutation(() => props.projectId)

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return '保存失败：不在当前阶段的可写范围内'
    if (err.status === 409) return '保存失败：项目正在运行中的一轮，请稍后再试'
    return typeof err.detail === 'string' ? err.detail : err.message
  }
  return err instanceof Error ? err.message : String(err)
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
async function onSave(): Promise<void> {
  if (!buffer.value) return
  saveError.value = null
  const content = buffer.value.content
  try {
    await writeMutation.mutateAsync({ path: props.path, stage: props.stage, content })
    buffer.value = saved(buffer.value, content)
  } catch (err) {
    saveError.value = describeError(err)
  }
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-2">
    <p
      v-if="missing"
      class="text-muted-foreground text-sm"
    >
      {{ emptyHint }}
    </p>
    <p
      v-else-if="isError"
      class="text-destructive text-sm"
    >
      读取 {{ path }} 失败。
    </p>
    <p
      v-else-if="!buffer"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
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

      <div
        v-if="mode === 'view'"
        class="min-h-0 flex-1 overflow-y-auto pr-1 text-sm"
        data-testid="markdown-view"
      >
        <MessageResponse
          :content="buffer.content"
          mode="static"
        />
      </div>
      <template v-else>
        <CodeEditor
          :content="buffer.content"
          language="markdown"
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
            v-else-if="buffer.dirty"
            class="text-muted-foreground text-xs"
          >
            有未保存的修改
          </span>
          <span v-else />
          <Button
            size="sm"
            :disabled="!buffer.dirty || busy || writeMutation.isPending.value"
            @click="onSave"
          >
            保存
          </Button>
        </div>
      </template>
    </template>
  </div>
</template>
