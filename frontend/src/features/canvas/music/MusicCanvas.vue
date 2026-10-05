<script setup lang="ts">
/**
 * 配乐阶段的画布（子项目 3 设计 §9.2）：三个标签。
 * - **播放**：试听、波形、段落与事件标记、指标与分析图；还没渲染时是空状态。
 * - **脚本**：编辑 `music/compose.py`，保存走普通的文件保存（阶段 `music`）；"渲染"按钮不经 agent，
 *   直接运行脚本并给出报告（旧产物在失败时不动）。有一轮在跑时只读、不能渲染。
 * - **事件**：声明的事件表，点一行回到播放标签并跳到该事件。
 * 三个标签都用 `v-show`，切换标签不会打断播放。定稿按钮等放在 `actions` 槽里。
 */
import { computed, nextTick, ref, watch, watchEffect } from 'vue'
import { Button } from '@/components/ui/button'
import CodeEditor from '@/components/CodeEditor.vue'
import { ApiError } from '@/api/http'
import {
  useFileContentQuery,
  useFileTreeQuery,
  useMusicMetaQuery,
  useRenderMusicMutation,
  useWriteFileMutation,
} from '@/composables/queries'
import {
  edit,
  initBuffer,
  keepMine,
  loadLatest,
  saved,
  serverUpdate,
  type BufferState,
} from '@/composables/conflictState'
import type { MusicRenderOut } from '@/types/api'
import EventTable from './EventTable.vue'
import MusicPlayer from './MusicPlayer.vue'
import RenderReport from './RenderReport.vue'

const props = defineProps<{
  projectId: string
  /** 当前项目是否有一轮正在跑；运行中编辑器只读、不能渲染。 */
  busy: boolean
}>()

const STAGE = 'music'
const SCRIPT = 'music/compose.py'

const tab = ref<'play' | 'script' | 'events'>('play')
const player = ref<InstanceType<typeof MusicPlayer> | null>(null)

const { data: meta, error: metaError } = useMusicMetaQuery(() => props.projectId)

function describeError(error: unknown): string {
  if (error instanceof ApiError) return typeof error.detail === 'string' ? error.detail : error.message
  return error instanceof Error ? error.message : '未知错误'
}
const metaProblem = computed(() =>
  metaError.value === null || metaError.value === undefined ? null : describeError(metaError.value),
)

async function onEventSeek(seconds: number): Promise<void> {
  tab.value = 'play'
  await nextTick()
  player.value?.seek(seconds)
}

// ---- 脚本缓冲区 ---------------------------------------------------------------------

const { data: fileTree } = useFileTreeQuery(() => props.projectId)
const scriptExists = computed(() => fileTree.value?.files.some((f) => f.path === SCRIPT) ?? false)
const { data: content } = useFileContentQuery(
  () => props.projectId,
  () => (scriptExists.value ? SCRIPT : null),
)

const buffer = ref<BufferState | null>(null)
watch(
  content,
  (text) => {
    if (text === undefined) return
    buffer.value = buffer.value === null ? initBuffer(text) : serverUpdate(buffer.value, text)
  },
  { immediate: true },
)
watchEffect(() => {
  if (fileTree.value === undefined || scriptExists.value || buffer.value !== null) return
  buffer.value = initBuffer('')
})

const readonly = computed(() => props.busy)
const writeMutation = useWriteFileMutation(() => props.projectId)
const saveError = ref<string | null>(null)

async function onSave(): Promise<void> {
  if (!buffer.value) return
  saveError.value = null
  try {
    await writeMutation.mutateAsync({ path: SCRIPT, stage: STAGE, content: buffer.value.content })
    buffer.value = saved(buffer.value, buffer.value.content)
  } catch (error) {
    saveError.value =
      error instanceof ApiError && error.status === 409
        ? '保存失败：项目正在运行中的一轮，请稍后再试'
        : `保存失败：${describeError(error)}`
  }
}

// ---- 手动渲染 ------------------------------------------------------------------------

const renderMutation = useRenderMusicMutation(() => props.projectId)
const report = ref<MusicRenderOut | null>(null)
const renderError = ref<string | null>(null)

const renderDisabledReason = computed<string | null>(() => {
  if (props.busy) return 'agent 正在运行，等它结束再渲染'
  if (renderMutation.isPending.value) return '正在渲染…'
  if (!scriptExists.value) return '还没有脚本，先写好并保存'
  if (buffer.value?.dirty) return '有未保存的修改，先保存再渲染'
  return null
})

async function onRender(): Promise<void> {
  if (renderDisabledReason.value !== null) return
  renderError.value = null
  try {
    report.value = await renderMutation.mutateAsync()
  } catch (error) {
    report.value = null
    renderError.value = describeError(error)
  }
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div
      class="flex flex-wrap items-center gap-1 text-sm"
      data-testid="music-tabbar"
    >
      <button
        v-for="item in [
          { id: 'play', label: '播放' },
          { id: 'script', label: '脚本' },
          { id: 'events', label: `事件（${meta?.events.length ?? 0}）` },
        ] as const"
        :key="item.id"
        type="button"
        class="rounded px-3 py-1 whitespace-nowrap"
        :class="tab === item.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        :data-testid="`music-tab-${item.id}`"
        @click="tab = item.id"
      >
        {{ item.label }}
      </button>
      <div class="ml-auto flex items-center gap-2">
        <slot name="actions" />
      </div>
    </div>

    <p
      v-if="metaProblem"
      class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm"
      role="alert"
      data-testid="music-problem"
    >
      {{ metaProblem }}
    </p>
    <p
      v-else-if="meta?.stale"
      class="rounded border border-amber-500 bg-amber-500/10 px-3 py-2 text-sm"
      role="status"
      data-testid="music-stale"
    >
      这份配乐是对着旧版节拍脚本或旁白渲染的，成片会拒绝它。到「脚本」标签重新渲染。
    </p>

    <div
      v-show="tab === 'play'"
      class="flex min-h-0 flex-1 flex-col"
    >
      <MusicPlayer
        v-if="meta?.rendered"
        ref="player"
        :project-id="projectId"
        :meta="meta"
      />
      <p
        v-else-if="meta"
        class="text-muted-foreground text-sm"
        data-testid="music-empty"
      >
        还没有渲染配乐。让 agent 写合成脚本，或到「脚本」标签自己写、保存后点渲染。
      </p>
      <p
        v-else-if="!metaProblem"
        class="text-muted-foreground text-sm"
      >
        加载中…
      </p>
    </div>

    <div
      v-show="tab === 'script'"
      class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto"
    >
      <template v-if="buffer">
        <div
          v-if="buffer.conflict"
          class="border-destructive bg-destructive/10 flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm"
        >
          <span>脚本在你编辑期间被更新了（可能是 agent 写的）。</span>
          <div class="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              @click="buffer = keepMine(buffer)"
            >
              保留我的修改
            </Button>
            <Button
              size="sm"
              variant="outline"
              @click="buffer = loadLatest(buffer)"
            >
              载入最新
            </Button>
          </div>
        </div>
        <div class="min-h-72 flex-1">
          <CodeEditor
            :content="buffer.content"
            language="python"
            :readonly="readonly"
            @update:content="(text: string) => (buffer = edit(buffer!, text))"
          />
        </div>
        <div class="flex shrink-0 items-center justify-between gap-2">
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
            v-else-if="!scriptExists"
            class="text-muted-foreground text-xs"
          >
            还没有脚本，写完后保存即可创建 {{ SCRIPT }}
          </span>
          <span
            v-else-if="buffer.dirty"
            class="text-muted-foreground text-xs"
          >
            有未保存的修改
          </span>
          <span v-else />
          <div class="flex items-center gap-2">
            <Button
              size="sm"
              :disabled="!buffer.dirty || readonly || writeMutation.isPending.value"
              data-testid="music-save"
              @click="onSave"
            >
              保存
            </Button>
            <Button
              size="sm"
              variant="outline"
              :disabled="renderDisabledReason !== null"
              :title="renderDisabledReason ?? '运行脚本并更新配乐'"
              data-testid="music-render"
              @click="onRender"
            >
              {{ renderMutation.isPending.value ? '渲染中…' : '渲染' }}
            </Button>
          </div>
        </div>
        <p
          v-if="renderDisabledReason && !renderMutation.isPending.value"
          class="text-muted-foreground text-xs"
          data-testid="music-render-hint"
        >
          {{ renderDisabledReason }}
        </p>
      </template>
      <p
        v-else
        class="text-muted-foreground text-sm"
      >
        加载中…
      </p>
      <p
        v-if="renderError"
        class="border-destructive bg-destructive/10 rounded border px-3 py-2 text-sm"
        role="alert"
        data-testid="music-render-error"
      >
        {{ renderError }}
      </p>
      <RenderReport
        v-if="report"
        :report="report"
        class="shrink-0"
      />
    </div>

    <div
      v-show="tab === 'events'"
      class="min-h-0 flex-1 overflow-y-auto"
    >
      <EventTable
        :events="meta?.events ?? []"
        @seek="onEventSeek"
      />
    </div>
  </div>
</template>
