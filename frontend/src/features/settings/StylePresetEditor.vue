<script setup lang="ts">
/**
 * 一套风格的编辑器（计划 M5 T11）。`presetId` 为 `null` 是新建草稿；父组件用 `:key` 在切换
 * 预设时整体重建它，所以内部状态不需要处理「换了另一套」。
 *
 * 一套风格是 skill 形态的目录（ADR 0011）：入口 `STYLE.md` + `references/*.md` + `exemplars/*`。
 * 左边是文件树，右边是 CodeMirror。保存前用 `styleDraft.ts::validateDraft` 检查（与后端规则一致），
 * 后端的校验错误（422，逐条点名到文件）原样显示。风格是**复制**进新项目的（决策 D5）：改风格库
 * 不影响已有项目，界面上写明。
 */
import { computed, ref, watch } from 'vue'
import { errorMessage } from '@/api/http'
import CodeEditor from '@/components/CodeEditor.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useCreateStylePresetMutation,
  useDeleteStylePresetMutation,
  useDuplicateStylePresetMutation,
  usePatchSettingsMutation,
  useStylePresetQuery,
  useUpdateStylePresetMutation,
} from '@/composables/queries'
import type { StylePresetOut } from '@/types/api'
import {
  addFile,
  draftFromPreset,
  draftToCreate,
  draftToPatch,
  emptyDraft,
  fileLanguage,
  isDirty,
  removeFile,
  updateFileText,
  validateDraft,
  type StyleDir,
  type StyleDraft,
} from './styleDraft'

const props = defineProps<{ presetId: string | null }>()
const emit = defineEmits<{
  (e: 'saved', id: string): void
  (e: 'deleted'): void
  (e: 'duplicated', id: string): void
  (e: 'dirty', value: boolean): void
}>()

const { data: loaded, isPending, error: loadError } = useStylePresetQuery(() => props.presetId)
const createMutation = useCreateStylePresetMutation()
const updateMutation = useUpdateStylePresetMutation()
const deleteMutation = useDeleteStylePresetMutation()
const duplicateMutation = useDuplicateStylePresetMutation()
const settingsMutation = usePatchSettingsMutation()

/** 当前编辑的是入口，还是某个引用/金样本文件。 */
type Selection = { kind: 'entry' } | { kind: 'file'; dir: StyleDir; name: string }

const original = ref<StylePresetOut | null>(null)
const draft = ref<StyleDraft>(emptyDraft())
const selection = ref<Selection>({ kind: 'entry' })
const problems = ref<string[]>([])
const addingDir = ref<StyleDir | null>(null)
const newFileName = ref('')
const addError = ref<string | null>(null)
const deleteDialogOpen = ref(false)

watch(
  loaded,
  (preset) => {
    if (preset && props.presetId !== null) {
      original.value = preset
      draft.value = draftFromPreset(preset)
    }
  },
  { immediate: true },
)

const dirty = computed(() => isDirty(draft.value, original.value))
watch(dirty, (value) => emit('dirty', value), { immediate: true })

const isNew = computed(() => props.presetId === null)
const busy = computed(
  () =>
    createMutation.isPending.value ||
    updateMutation.isPending.value ||
    deleteMutation.isPending.value ||
    duplicateMutation.isPending.value ||
    settingsMutation.isPending.value,
)

const currentText = computed(() => {
  const sel = selection.value
  if (sel.kind === 'entry') return draft.value.content
  return draft.value[sel.dir].find((f) => f.name === sel.name)?.text ?? ''
})
const currentLabel = computed(() => {
  const sel = selection.value
  return sel.kind === 'entry' ? 'STYLE.md' : `${sel.dir}/${sel.name}`
})
const currentLanguage = computed(() =>
  selection.value.kind === 'entry' ? 'markdown' : fileLanguage(selection.value.name),
)
const editorKey = computed(() => currentLabel.value)

function setText(text: string): void {
  const sel = selection.value
  draft.value =
    sel.kind === 'entry'
      ? { ...draft.value, content: text }
      : updateFileText(draft.value, sel.dir, sel.name, text)
}

function isSelected(dir: StyleDir, name: string): boolean {
  const sel = selection.value
  return sel.kind === 'file' && sel.dir === dir && sel.name === name
}

function startAdd(dir: StyleDir): void {
  addingDir.value = dir
  newFileName.value = ''
  addError.value = null
}

function confirmAdd(): void {
  if (addingDir.value === null) return
  const result = addFile(draft.value, addingDir.value, newFileName.value)
  if (result.error) {
    addError.value = result.error
    return
  }
  draft.value = result.draft
  selection.value = { kind: 'file', dir: addingDir.value, name: newFileName.value.trim() }
  addingDir.value = null
}

function deleteFile(dir: StyleDir, name: string): void {
  draft.value = removeFile(draft.value, dir, name)
  if (isSelected(dir, name)) selection.value = { kind: 'entry' }
}

function discard(): void {
  draft.value = original.value ? draftFromPreset(original.value) : emptyDraft()
  selection.value = { kind: 'entry' }
  problems.value = []
}

const serverError = computed(() => {
  const error = createMutation.error.value ?? updateMutation.error.value
  return error ? errorMessage(error) : null
})

async function save(): Promise<void> {
  problems.value = validateDraft(draft.value)
  if (problems.value.length > 0) return
  try {
    if (props.presetId === null) {
      const created = await createMutation.mutateAsync(draftToCreate(draft.value))
      emit('saved', created.id)
      return
    }
    if (!original.value) return
    const patch = draftToPatch(draft.value, original.value)
    if (Object.keys(patch).length === 0) return
    const updated = await updateMutation.mutateAsync({ id: props.presetId, patch })
    original.value = updated
    draft.value = draftFromPreset(updated)
    emit('saved', updated.id)
  } catch {
    // 后端的校验错误显示在下面（serverError）。
  }
}

async function duplicate(): Promise<void> {
  if (props.presetId === null) return
  try {
    const copy = await duplicateMutation.mutateAsync(props.presetId)
    emit('duplicated', copy.id)
  } catch {
    // 罕见（名字冲突已由后端自动避开）；错误留在 duplicateMutation 里。
  }
}

async function toggleDefault(): Promise<void> {
  if (props.presetId === null || !original.value) return
  const makeDefault = !original.value.is_default
  await settingsMutation.mutateAsync({
    default_style_preset_id: makeDefault ? props.presetId : null,
  })
  original.value = { ...original.value, is_default: makeDefault }
}

async function confirmDelete(): Promise<void> {
  if (props.presetId === null) return
  try {
    await deleteMutation.mutateAsync(props.presetId)
    deleteDialogOpen.value = false
    emit('deleted')
  } catch {
    deleteDialogOpen.value = false
  }
}

const DIRS: { dir: StyleDir; title: string; hint: string }[] = [
  { dir: 'references', title: '引用文件', hint: 'references/*.md' },
  { dir: 'exemplars', title: '金样本', hint: 'exemplars/*.json|md' },
]
</script>

<template>
  <div class="flex min-w-0 flex-1 flex-col gap-3">
    <p
      v-if="!isNew && isPending"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
    <p
      v-else-if="loadError"
      class="text-destructive text-sm"
    >
      加载失败：{{ errorMessage(loadError) }}
    </p>

    <template v-else>
      <div class="grid grid-cols-3 gap-3">
        <div class="flex flex-col gap-1.5">
          <Label for="style-name">名称</Label>
          <Input
            id="style-name"
            v-model="draft.name"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="style-category">分类</Label>
          <Input
            id="style-category"
            v-model="draft.category"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="style-description">简介（留空取入口的 description）</Label>
          <Input
            id="style-description"
            v-model="draft.description"
          />
        </div>
      </div>

      <div class="flex min-h-[420px] gap-3">
        <div class="flex w-56 shrink-0 flex-col gap-3 overflow-y-auto rounded-md border p-2 text-sm">
          <button
            type="button"
            class="hover:bg-muted rounded px-2 py-1 text-left font-medium"
            :class="{ 'bg-muted': selection.kind === 'entry' }"
            data-testid="file-entry"
            @click="selection = { kind: 'entry' }"
          >
            STYLE.md（入口）
          </button>

          <div
            v-for="group in DIRS"
            :key="group.dir"
            class="flex flex-col gap-1"
          >
            <div class="text-muted-foreground flex items-center justify-between px-2 text-xs">
              <span>{{ group.title }}（{{ draft[group.dir].length }}）</span>
              <button
                type="button"
                class="hover:text-foreground"
                :data-testid="`add-${group.dir}`"
                @click="startAdd(group.dir)"
              >
                ＋添加
              </button>
            </div>
            <div
              v-for="file in draft[group.dir]"
              :key="file.name"
              class="hover:bg-muted group flex items-center justify-between rounded px-2 py-1"
              :class="{ 'bg-muted': isSelected(group.dir, file.name) }"
            >
              <button
                type="button"
                class="min-w-0 flex-1 truncate text-left"
                :data-testid="`file-${group.dir}-${file.name}`"
                @click="selection = { kind: 'file', dir: group.dir, name: file.name }"
              >
                {{ file.name }}
              </button>
              <button
                type="button"
                class="text-muted-foreground hover:text-destructive ml-1"
                :title="`删除 ${file.name}`"
                @click="deleteFile(group.dir, file.name)"
              >
                ×
              </button>
            </div>
            <div
              v-if="addingDir === group.dir"
              class="flex flex-col gap-1 px-1"
            >
              <Input
                v-model="newFileName"
                :placeholder="group.hint"
                :data-testid="`new-file-${group.dir}`"
                @keydown.enter="confirmAdd"
                @keydown.esc="addingDir = null"
              />
              <p
                v-if="addError"
                class="text-destructive text-xs"
              >
                {{ addError }}
              </p>
            </div>
          </div>
        </div>

        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <div class="text-muted-foreground font-mono text-xs">
            {{ currentLabel }}
          </div>
          <div class="min-h-0 flex-1 overflow-hidden rounded-md border">
            <CodeEditor
              :key="editorKey"
              :content="currentText"
              :language="currentLanguage"
              :readonly="false"
              @update:content="setText"
            />
          </div>
        </div>
      </div>

      <ul
        v-if="problems.length"
        class="border-destructive/50 bg-destructive/5 text-destructive flex flex-col gap-0.5 rounded-md border p-3 text-sm"
        data-testid="style-problems"
      >
        <li
          v-for="problem in problems"
          :key="problem"
        >
          {{ problem }}
        </li>
      </ul>
      <p
        v-if="serverError"
        class="text-destructive text-sm"
        data-testid="style-server-error"
      >
        保存失败：{{ serverError }}
      </p>
      <p class="text-muted-foreground text-xs">
        风格是创建项目时<strong>复制</strong>进项目 style/ 目录的，改这里不影响已有项目。
      </p>

      <div class="flex flex-wrap items-center gap-2">
        <Button
          :disabled="busy || (!isNew && !dirty)"
          data-testid="save-style"
          @click="save"
        >
          {{ isNew ? '创建' : '保存' }}
        </Button>
        <Button
          variant="outline"
          :disabled="busy || !dirty"
          @click="discard"
        >
          放弃修改
        </Button>
        <template v-if="!isNew && original">
          <Badge
            v-if="original.is_default"
            variant="secondary"
          >
            默认风格
          </Badge>
          <Button
            variant="outline"
            :disabled="busy"
            data-testid="toggle-default"
            @click="toggleDefault"
          >
            {{ original.is_default ? '取消默认' : '设为默认' }}
          </Button>
          <Button
            variant="outline"
            :disabled="busy || dirty"
            :title="dirty ? '先保存或放弃修改' : ''"
            data-testid="duplicate-style"
            @click="duplicate"
          >
            复制
          </Button>
          <Button
            variant="ghost"
            :disabled="busy"
            data-testid="delete-style"
            @click="deleteDialogOpen = true"
          >
            删除
          </Button>
        </template>
      </div>

      <AlertDialog v-model:open="deleteDialogOpen">
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除风格 {{ original?.name }}？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后不能恢复。已经用它创建的项目不受影响（风格是复制进项目的）；如果它是默认风格，默认风格会被清空。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction @click="confirmDelete">
              确认删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </template>
  </div>
</template>
