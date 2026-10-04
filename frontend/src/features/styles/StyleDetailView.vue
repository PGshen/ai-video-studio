<script setup lang="ts">
/**
 * 风格详情态（计划 style-library T7）：只读显示正式版本——名称/分类/简介、文件树和文件内容；
 * 按钮「编辑」「设为默认/取消默认」「复制」「删除」。有未保存草稿时提示（草稿在编辑态里继续）。
 */
import { computed, ref, watch } from 'vue'
import { errorMessage } from '@/api/http'
import CodeEditor from '@/components/CodeEditor.vue'
import ConfirmDeleteButton from '@/components/ConfirmDeleteButton.vue'
import SafeMarkdown from '@/components/session/SafeMarkdown.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useDeleteStyleMutation,
  useDuplicateStyleMutation,
  usePatchSettingsMutation,
  useStyleQuery,
  useStylesQuery,
} from '@/composables/queries'
import StyleFileTree from './StyleFileTree.vue'
import { stripFrontmatter } from './styleFrontmatter'
import { ENTRY_FILE, languageOf } from './styleFiles'

const props = defineProps<{ styleId: string }>()
const emit = defineEmits<{
  (e: 'edit'): void
  (e: 'close'): void
  (e: 'open', styleId: string): void
}>()

const { data: style, isError, error } = useStyleQuery(() => props.styleId)
const { data: summaries } = useStylesQuery()
const hasDraft = computed(
  () => summaries.value?.find((s) => s.id === props.styleId)?.has_draft ?? false,
)

const files = computed(() => Object.keys(style.value?.files ?? {}).sort())
const active = ref('STYLE.md')
watch(
  () => props.styleId,
  () => (active.value = 'STYLE.md'),
)
const content = computed(() => style.value?.files[active.value] ?? '')
/** markdown 文件直接渲染；json 金样本仍用只读编辑器。入口的 frontmatter 已在标题区显示，渲染时去掉。 */
const isMarkdown = computed(() => languageOf(active.value) === 'markdown')
const rendered = computed(() =>
  active.value === ENTRY_FILE ? stripFrontmatter(content.value) : content.value,
)

const patchSettings = usePatchSettingsMutation()
const duplicateMutation = useDuplicateStyleMutation()
const deleteMutation = useDeleteStyleMutation()
const actionError = ref<string | null>(null)

async function run(action: () => Promise<void>): Promise<void> {
  actionError.value = null
  try {
    await action()
  } catch (e) {
    actionError.value = errorMessage(e)
  }
}

const toggleDefault = () =>
  run(async () => {
    await patchSettings.mutateAsync({
      default_style_preset_id: style.value?.is_default ? null : props.styleId,
    })
  })

const duplicate = () =>
  run(async () => {
    const copy = await duplicateMutation.mutateAsync(props.styleId)
    emit('open', copy.id)
  })

async function remove(): Promise<void> {
  await deleteMutation.mutateAsync(props.styleId)
  emit('close')
}
</script>

<template>
  <p
    v-if="isError"
    class="text-muted-foreground text-sm"
    data-testid="style-not-found"
  >
    {{ (error as { status?: number } | null)?.status === 404 ? '风格不存在，可能已被删除。' : '风格加载失败。' }}
  </p>
  <p
    v-else-if="!style"
    class="text-muted-foreground text-sm"
  >
    加载中…
  </p>

  <div
    v-else
    class="flex min-h-0 flex-1 flex-col gap-3"
  >
    <div class="flex flex-col gap-2">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-lg font-semibold">
          {{ style.name }}
        </h3>
        <Badge variant="outline">
          {{ style.category }}
        </Badge>
        <Badge v-if="style.is_default">
          默认
        </Badge>
      </div>
      <p
        v-if="style.description"
        class="text-muted-foreground text-sm"
      >
        {{ style.description }}
      </p>
      <p
        v-if="hasDraft"
        class="text-muted-foreground text-xs"
        data-testid="style-draft-notice"
      >
        这套风格有未保存的草稿；这里显示的是已保存的版本，点「编辑」继续修改草稿。
      </p>
    </div>

    <div
      class="grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] gap-3 md:grid-cols-[14rem_minmax(0,1fr)] md:grid-rows-1"
    >
      <div class="max-h-36 overflow-y-auto rounded-md border p-2 md:max-h-none">
        <StyleFileTree
          v-model:active="active"
          :files="files"
          readonly
        />
      </div>
      <div
        v-if="isMarkdown"
        class="min-h-0 overflow-auto rounded-md border p-4"
        data-testid="markdown-pane"
      >
        <SafeMarkdown
          :content="rendered"
          mode="static"
        />
      </div>
      <div
        v-else
        class="flex min-h-0 flex-col"
      >
        <CodeEditor
          :key="active"
          :content="content"
          :language="languageOf(active)"
          readonly
        />
      </div>
    </div>

    <p
      v-if="actionError"
      class="text-destructive text-sm"
    >
      操作失败：{{ actionError }}
    </p>
    <div class="flex shrink-0 flex-wrap items-center gap-2">
      <Button
        data-testid="detail-edit"
        @click="emit('edit')"
      >
        编辑
      </Button>
      <Button
        variant="outline"
        :disabled="patchSettings.isPending.value"
        data-testid="toggle-default"
        @click="toggleDefault"
      >
        {{ style.is_default ? '取消默认' : '设为默认' }}
      </Button>
      <Button
        variant="outline"
        :disabled="duplicateMutation.isPending.value"
        data-testid="duplicate-style"
        @click="duplicate"
      >
        复制
      </Button>
      <ConfirmDeleteButton
        test-id="style-delete"
        :title="`删除风格「${style.name}」？`"
        description="删除后不能恢复；已用它创建的项目不受影响（风格是复制进项目的）。"
        :action="remove"
      />
    </div>
  </div>
</template>
