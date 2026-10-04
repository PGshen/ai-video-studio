<script setup lang="ts">
/**
 * 风格编辑态（计划 style-library T7）：名称/分类/简介表单 + 文件树 + 代码编辑器，底部「保存」「放弃修改」。
 * 所有改动先写进服务端草稿（`useStyleDraft`），点「保存」校验通过才成为正式版本。`readonly` 时（AI
 * 正在修改）整个编辑区只读；`chat` 插槽放右侧的对话区（T10）。
 */
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/CodeEditor.vue'
import type { StyleOut } from '@/types/api'
import StyleFileTree from './StyleFileTree.vue'
import StyleMetaForm from './StyleMetaForm.vue'
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

const stateText = computed(() => {
  if (props.readonly && props.readonlyReason) return props.readonlyReason
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
  const { wasNew } = await draft.discard()
  emit('discarded', wasNew)
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
    class="flex min-h-0 flex-1 gap-4"
  >
    <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
      <StyleMetaForm
        :meta="draft.meta.value"
        :readonly="readonly"
        @update="draft.updateMeta"
      />

      <div
        class="grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-3 md:grid-cols-[14rem_minmax(0,1fr)] md:grid-rows-1"
      >
        <div class="max-h-36 overflow-y-auto rounded-md border p-2 md:max-h-none">
          <StyleFileTree
            :active="draft.activePath.value"
            :files="draft.files.value"
            :readonly="readonly"
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
            :readonly="readonly ?? false"
            @update:content="draft.edit(draft.activePath.value, $event)"
          />
        </div>
      </div>

      <p
        v-if="draft.saveError.value"
        class="text-destructive text-sm"
        data-testid="style-server-error"
      >
        {{ draft.saveError.value }}
      </p>
      <div class="flex shrink-0 items-center gap-2">
        <Button
          :disabled="readonly || draft.saving.value"
          data-testid="save-style"
          @click="save"
        >
          保存
        </Button>
        <Button
          variant="outline"
          :disabled="readonly || draft.saving.value"
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
    <slot name="chat" />
  </div>
</template>
