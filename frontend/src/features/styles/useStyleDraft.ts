/**
 * 一套风格的草稿编辑（计划 style-library T7）：打开草稿、读写草稿文件、防抖写入、改 frontmatter、
 * 增删文件、保存和放弃。草稿在服务端（`data/style-drafts/<id>/`），前端不持有整包内容：
 *
 * - `edit` 先写进查询缓存（编辑器立即看到），600ms 防抖后 PUT 到草稿文件；写入按文件串行，
 *   失败的编辑会留着等下一次 `flush`，保存前会先 `flush`，写不进去就不保存；
 * - 写入直接调接口、不走 mutation：组件卸载（关闭抽屉）时 `flush` 仍然要能把编辑写出去；
 * - 名称、简介、分类是 `STYLE.md` 的 frontmatter，`updateMeta` 就是改这个文件；
 * - 截图（ADR 0022）不走防抖：上传、删除、调整顺序都是立即调接口，成功后用返回的草稿状态刷新缓存，
 *   同样只在草稿里生效，保存或放弃时和文本一起处理。
 */
import { useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import * as api from '@/api/endpoints'
import { ApiError, errorMessage } from '@/api/http'
import {
  invalidateStyleDraft,
  queryKeys,
  useDeleteDraftFileMutation,
  useDiscardStyleDraftMutation,
  useDraftFileQuery,
  useOpenStyleDraftMutation,
  useSaveStyleDraftMutation,
  useStyleDraftQuery,
} from '@/composables/queries'
import type { DraftStatusOut, StyleOut } from '@/types/api'
import { readStyleMeta, updateFrontmatter, type StyleMeta } from './styleFrontmatter'

export const ENTRY_PATH = 'STYLE.md'
export const WRITE_DEBOUNCE_MS = 600

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

interface PendingWrite {
  id: string
  path: string
  text: string
}

export function useStyleDraft(styleIdSource: MaybeRefOrGetter<string>) {
  const styleId = computed(() => toValue(styleIdSource))
  const queryClient = useQueryClient()
  const openMutation = useOpenStyleDraftMutation()
  const saveMutation = useSaveStyleDraftMutation()
  const discardMutation = useDiscardStyleDraftMutation()
  const deleteFileMutation = useDeleteDraftFileMutation(styleId)

  const activePath = ref(ENTRY_PATH)
  const opened = ref(false)
  const openError = ref<unknown>(null)
  watch(
    styleId,
    async (id) => {
      opened.value = false
      openError.value = null
      activePath.value = ENTRY_PATH
      try {
        await openMutation.mutateAsync(id)
        if (id === styleId.value) opened.value = true
      } catch (error) {
        if (id === styleId.value) openError.value = error
      }
    },
    { immediate: true },
  )

  const statusQuery = useStyleDraftQuery(styleId, opened)
  const activeQuery = useDraftFileQuery(styleId, activePath, opened)
  const entryQuery = useDraftFileQuery(styleId, ENTRY_PATH, opened)

  /** 草稿已打开且状态、入口内容都读到了（表单和文件树据此显示，避免先闪一下空白）。 */
  const ready = computed(
    () =>
      opened.value && statusQuery.data.value !== undefined && entryQuery.data.value !== undefined,
  )
  /** 当前选中的文件内容也读到了（切换文件时编辑器据此显示）。 */
  const contentReady = computed(() => ready.value && activeQuery.data.value !== undefined)
  const notFound = computed(
    () => openError.value instanceof ApiError && openError.value.status === 404,
  )
  const openErrorMessage = computed(() =>
    openError.value === null ? null : errorMessage(openError.value),
  )
  const files = computed(() => statusQuery.data.value?.files ?? [])
  const isNew = computed(() => statusQuery.data.value?.is_new ?? false)
  /** AI 正在改这份草稿（后端的 `busy`）：编辑区只读，轮次结束后刷新草稿即恢复。 */
  const busy = computed(() => statusQuery.data.value?.busy ?? false)
  const screenshots = computed(() => statusQuery.data.value?.screenshots ?? [])
  const content = computed(() => activeQuery.data.value ?? '')
  const entryText = computed(() => entryQuery.data.value ?? '')
  const meta = computed(() => readStyleMeta(entryText.value))

  // ---- 防抖写入 ----------------------------------------------------------

  const saveState = ref<SaveState>('idle')
  const writeError = ref<string | null>(null)
  const pending = new Map<string, PendingWrite>()
  const timers = new Map<string, ReturnType<typeof setTimeout>>()
  const chains = new Map<string, Promise<void>>()
  let active = 0

  const keyOf = (id: string, path: string) => `${id}\u0000${path}`

  async function write(key: string): Promise<void> {
    const item = pending.get(key)
    if (item === undefined) return
    pending.delete(key)
    clearTimeout(timers.get(key))
    timers.delete(key)
    const run = async () => {
      active += 1
      saveState.value = 'saving'
      try {
        const status = await api.writeDraftFile(item.id, item.path, item.text)
        queryClient.setQueryData(queryKeys.styleDraft(item.id), status)
        writeError.value = null
        if (pending.size === 0 && active === 1) saveState.value = 'saved'
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          // AI 正在修改这份草稿：这条编辑不能留着事后重放，否则会悄悄覆盖 AI 的成果。丢弃它，
          // 并让草稿重新取一遍（轮次结束时界面显示的是服务端的内容）。
          writeError.value = null
          saveState.value = pending.size === 0 ? 'idle' : 'pending'
          invalidateStyleDraft(queryClient, item.id)
        } else {
          // 其他失败：留着等下一次 flush / 新的编辑；比它更新的编辑不被覆盖。
          if (!pending.has(key)) pending.set(key, item)
          writeError.value = errorMessage(error)
          saveState.value = 'error'
        }
      } finally {
        active -= 1
      }
    }
    const next = (chains.get(key) ?? Promise.resolve()).then(run)
    chains.set(key, next)
    await next
  }

  async function flush(): Promise<void> {
    await Promise.all([...pending.keys()].map(write))
    await Promise.all([...chains.values()])
  }

  function edit(path: string, text: string): void {
    const id = styleId.value
    const key = keyOf(id, path)
    queryClient.setQueryData(queryKeys.styleDraftFile(id, path), text)
    pending.set(key, { id, path, text })
    saveState.value = 'pending'
    clearTimeout(timers.get(key))
    timers.set(
      key,
      setTimeout(() => void write(key), WRITE_DEBOUNCE_MS),
    )
  }

  function updateMeta(patch: Partial<StyleMeta>): void {
    const base =
      queryClient.getQueryData<string>(queryKeys.styleDraftFile(styleId.value, ENTRY_PATH)) ??
      entryText.value
    edit(ENTRY_PATH, updateFrontmatter(base, patch))
  }

  /** 把还没写出的编辑全部写进草稿；写不进去就抛错（发消息给 AI、保存之前都要先过这一关）。 */
  async function ensureWritten(): Promise<void> {
    await flush()
    if (saveState.value === 'error') {
      throw new Error(`草稿还没有写入成功：${writeError.value ?? '未知错误'}`)
    }
  }

  onBeforeUnmount(() => void flush())

  // ---- 文件与保存 --------------------------------------------------------

  function selectFile(path: string): void {
    activePath.value = path
  }

  async function addFile(directory: 'references' | 'exemplars', name: string): Promise<void> {
    const path = `${directory}/${name}`
    edit(path, '')
    await write(keyOf(styleId.value, path))
    activePath.value = path
  }

  async function removeFile(path: string): Promise<void> {
    const key = keyOf(styleId.value, path)
    pending.delete(key)
    clearTimeout(timers.get(key))
    await deleteFileMutation.mutateAsync(path)
    queryClient.removeQueries({ queryKey: queryKeys.styleDraftFile(styleId.value, path) })
    if (activePath.value === path) activePath.value = ENTRY_PATH
  }

  const saving = ref(false)
  const saveError = ref<string | null>(null)

  /** 保存：先写出未写入的编辑，成功返回正式版本；失败返回 `null`，原因在 `saveError`，草稿保留。 */
  async function save(): Promise<StyleOut | null> {
    saveError.value = null
    saving.value = true
    try {
      try {
        await ensureWritten()
      } catch (error) {
        saveError.value = `${errorMessage(error)}，没有保存`
        return null
      }
      return await saveMutation.mutateAsync(styleId.value)
    } catch (error) {
      saveError.value = errorMessage(error)
      return null
    } finally {
      saving.value = false
    }
  }

  // ---- 截图 ---------------------------------------------------------------

  const screenshotError = ref<string | null>(null)
  const uploading = ref(false)

  /** 跑一次截图改动：成功后用返回的草稿状态刷新；409（AI 正在改）不报错，重新取草稿；其他失败
   * 写进 `screenshotError` 并返回 `false`。 */
  async function runScreenshotAction(
    id: string,
    action: () => Promise<DraftStatusOut>,
  ): Promise<boolean> {
    try {
      const status = await action()
      queryClient.setQueryData(queryKeys.styleDraft(id), status)
      return true
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        invalidateStyleDraft(queryClient, id)
      } else {
        screenshotError.value = errorMessage(error)
      }
      return false
    }
  }

  /** 逐个上传图片（跳过不是图片的文件）；遇到失败就停止，已经成功的保留。 */
  async function uploadScreenshots(selected: readonly File[]): Promise<void> {
    const id = styleId.value
    screenshotError.value = null
    uploading.value = true
    try {
      for (const file of selected) {
        if (!file.type.startsWith('image/')) continue
        if (!(await runScreenshotAction(id, () => api.uploadStyleScreenshot(id, file)))) break
      }
    } finally {
      uploading.value = false
    }
  }

  async function removeScreenshot(name: string): Promise<void> {
    const id = styleId.value
    screenshotError.value = null
    await runScreenshotAction(id, () => api.deleteStyleScreenshot(id, name))
  }

  /** 把 `name` 移到第 `to` 个位置（0 = 封面）；位置越界或没有变化时什么都不做。 */
  async function moveScreenshot(name: string, to: number): Promise<void> {
    const id = styleId.value
    const names = [...screenshots.value]
    const from = names.indexOf(name)
    if (from < 0 || to < 0 || to >= names.length || to === from) return
    names.splice(from, 1)
    names.splice(to, 0, name)
    screenshotError.value = null
    await runScreenshotAction(id, () => api.reorderStyleScreenshots(id, names))
  }

  const discardError = ref<string | null>(null)

  /** 放弃草稿；`wasNew` 为真表示这是从未保存过的新风格，整个消失。后端拒绝（例如 AI 正在修改）时
   * 返回 `null`，原因在 `discardError`，草稿和还没写出的编辑都保留。 */
  async function discard(): Promise<{ wasNew: boolean } | null> {
    const wasNew = isNew.value
    discardError.value = null
    const held = [...pending.values()]
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    pending.clear()
    try {
      await discardMutation.mutateAsync(styleId.value)
    } catch (error) {
      for (const item of held) edit(item.path, item.text)
      discardError.value = errorMessage(error)
      return null
    }
    return { wasNew }
  }

  return {
    ready,
    contentReady,
    notFound,
    openErrorMessage,
    files,
    isNew,
    busy,
    screenshots,
    screenshotError,
    uploading,
    uploadScreenshots,
    removeScreenshot,
    moveScreenshot,
    activePath,
    selectFile,
    content,
    entryText,
    meta,
    edit,
    updateMeta,
    addFile,
    removeFile,
    saveState,
    writeError,
    flush,
    ensureWritten,
    saving,
    saveError,
    save,
    discard,
    discardError,
  }
}
