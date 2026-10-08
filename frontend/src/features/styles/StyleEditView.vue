<script setup lang="ts">
/**
 * 风格编辑态（计划 style-library T7）：名称/分类/简介表单 + 文件树 + 代码编辑器，底部「保存」「放弃修改」。
 * 所有改动先写进服务端草稿（`useStyleDraft`），点「保存」校验通过才成为正式版本。右侧是 AI 对话区
 * （`StyleChatPane`）：AI 改的是同一份草稿；后端报告 AI 正在修改（`busy`）或 `readonly` 时整个
 * 编辑区只读，轮次结束后恢复。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/CodeEditor.vue'
import type { StyleOut } from '@/types/api'
import StyleChatPane from './StyleChatPane.vue'
import StyleFileTree from './StyleFileTree.vue'
import StyleMetaForm from './StyleMetaForm.vue'
import StyleScreenshots from './StyleScreenshots.vue'
import { languageOf } from './styleFiles'
import { useStyleDraft } from './useStyleDraft'

const props = defineProps<{
  styleId: string
  readonly?: boolean
  /** 只读时显示的原因，例如「AI 正在修改」。 */
  readonlyReason?: string
}>()
const emit = defineEmits<{
  (e: 'saved', style: StyleOut): void
  (e: 'discarded', wasNew: boolean): void
  (e: 'close'): void
}>()

const draft = useStyleDraft(() => props.styleId)

/** 点发送到服务端 `busy` 接管之间的本地锁（对话区发 `sending`）：这段时间敲的字会被后端 409 丢弃。 */
const sending = ref(false)
watch(
  () => props.styleId,
  () => {
    sending.value = false
  },
)

/** 编辑区只读：外部要求，或 AI 正在修改这份草稿（含刚点发送、服务端状态还没到）。 */
const aiWorking = computed(() => draft.busy.value || sending.value)
const locked = computed(() => (props.readonly ?? false) || aiWorking.value)
const lockedReason = computed(
  () => props.readonlyReason ?? (aiWorking.value ? 'AI 正在修改，完成后可以继续编辑' : undefined),
)

/**
 * 粘贴剪贴板里的图片当截图上传。粘贴事件只发给有焦点的元素（没有就发给 body），所以监听在 `document`
 * 上，而不是截图区的容器——用户点一下空白处再 ⌘V 也要生效。剪贴板里没有图片时不拦截；焦点在输入框、
 * 编辑器里并且剪贴板同时带文本时，也不抢走粘贴（从网页复制的图文）。
 */
function onPaste(event: ClipboardEvent): void {
  if (locked.value || !draft.ready.value) return
  const data = event.clipboardData
  const images = Array.from(data?.files ?? []).filter((f) => f.type.startsWith('image/'))
  if (images.length === 0) return
  const target = event.target instanceof Element ? event.target : null
  const typing = target?.closest('input, textarea, [contenteditable=""], [contenteditable="true"]')
  if (typing && Array.from(data?.types ?? []).includes('text/plain')) return
  event.preventDefault()
  void draft.uploadScreenshots(images)
}
onMounted(() => document.addEventListener('paste', onPaste))
onBeforeUnmount(() => document.removeEventListener('paste', onPaste))

const stateText = computed(() => {
  if (locked.value && lockedReason.value) return lockedReason.value
  switch (draft.saveState.value) {
    case 'pending':
      return '待写入草稿…'
    case 'saving':
      return '正在写入草稿…'
    case 'saved':
      return '已保存到草稿'
    case 'error':
      return `写入草稿失败：${draft.writeError.value ?? '未知错误'}`
    default:
      return ''
  }
})

async function save(): Promise<void> {
  const saved = await draft.save()
  if (saved) emit('saved', saved)
}

async function discard(): Promise<void> {
  if (!window.confirm('放弃所有未保存的修改？这套风格会回到上次保存的样子。')) return
  const result = await draft.discard()
  if (result) emit('discarded', result.wasNew)
}
</script>

<template>
  <p
    v-if="draft.notFound.value"
    class="text-muted-foreground flex flex-col items-start gap-3 text-sm"
    data-testid="style-not-found"
  >
    风格不存在，可能已被删除。
    <Button
      size="sm"
      variant="outline"
      data-testid="style-not-found-close"
      @click="emit('close')"
    >
      关闭
    </Button>
  </p>
  <p
    v-else-if="draft.openErrorMessage.value"
    class="text-destructive text-sm"
  >
    打开草稿失败：{{ draft.openErrorMessage.value }}
  </p>
  <p
    v-else-if="!draft.ready.value"
    class="text-muted-foreground text-sm"
  >
    正在打开草稿…
  </p>

  <div
    v-else
    class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:flex-row lg:overflow-visible"
  >
    <div class="flex min-h-[28rem] min-w-0 flex-1 flex-col gap-3 lg:min-h-0">
      <StyleMetaForm
        :meta="draft.meta.value"
        :readonly="locked"
        @update="draft.updateMeta"
      />

      <div data-testid="style-screenshots-section">
        <StyleScreenshots
          :style-id="styleId"
          :names="draft.screenshots.value"
          :readonly="locked"
          :uploading="draft.uploading.value"
          @upload="draft.uploadScreenshots"
          @remove="draft.removeScreenshot"
          @move="draft.moveScreenshot"
        />
        <p
          v-if="draft.screenshotError.value"
          class="text-destructive mt-1 text-sm"
          data-testid="shot-error"
        >
          {{ draft.screenshotError.value }}
        </p>
      </div>

      <div
        class="grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-3 md:grid-cols-[14rem_minmax(0,1fr)] md:grid-rows-1"
      >
        <div class="max-h-36 overflow-y-auto rounded-md border p-2 md:max-h-none">
          <StyleFileTree
            :active="draft.activePath.value"
            :files="draft.files.value"
            :readonly="locked"
            @update:active="draft.selectFile"
            @add="draft.addFile"
            @remove="draft.removeFile"
          />
        </div>
        <div class="flex min-h-0 flex-col">
          <p
            v-if="!draft.contentReady.value"
            class="text-muted-foreground p-3 text-sm"
          >
            加载中…
          </p>
          <CodeEditor
            v-else
            :key="draft.activePath.value"
            :content="draft.content.value"
            :language="languageOf(draft.activePath.value)"
            :readonly="locked"
            @update:content="draft.edit(draft.activePath.value, $event)"
          />
        </div>
      </div>

      <p
        v-if="draft.saveError.value || draft.discardError.value"
        class="text-destructive text-sm"
        data-testid="style-server-error"
      >
        {{ draft.saveError.value ?? draft.discardError.value }}
      </p>
      <div class="flex shrink-0 items-center gap-2">
        <Button
          :disabled="locked || draft.saving.value || draft.uploading.value"
          data-testid="save-style"
          @click="save"
        >
          保存
        </Button>
        <Button
          variant="outline"
          :disabled="locked || draft.saving.value || draft.uploading.value"
          data-testid="discard-style"
          @click="discard"
        >
          放弃修改
        </Button>
        <span
          class="text-muted-foreground text-xs"
          data-testid="save-state"
        >
          {{ stateText }}
        </span>
      </div>
    </div>
    <StyleChatPane
      class="h-[28rem] shrink-0 lg:h-auto lg:w-96"
      :style-id="styleId"
      :before-send="draft.ensureWritten"
      @sending="sending = $event"
    />
  </div>
</template>
