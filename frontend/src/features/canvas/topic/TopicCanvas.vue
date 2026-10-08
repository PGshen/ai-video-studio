<script setup lang="ts">
/**
 * 选题打磨阶段画布（计划 M4 T11）：一行标签——「简报」（`topic/brief.md` 的渲染视图，可切换编辑）
 * 和「笔记」（`topic/notes/` 下的调研笔记，含项目创建时种进来的想法卡片 `idea-card.md`），
 * 标签行右侧是 `check_brief` 检查结果的状态图标、渲染/编辑切换和宿主塞进来的 `actions` 插槽（工作台放快照栏开关，canvas-layout）。状态都从通用文件
 * 端点读，检查结果来自 `GET /projects/{id}/topic/check`（和 `check_brief` 工具同一份逻辑）；
 * 文件变化时 `invalidateWorkspace` 会让检查查询一并失效。渲染/编辑模式由这里持有，
 * 简报和当前笔记共用；换标签、换笔记时回到渲染。
 */
import { computed, ref, watch } from 'vue'
import { useFileTreeQuery, useTopicCheckQuery } from '@/composables/queries'
import BriefStatusIcon from './BriefStatusIcon.vue'
import EditModeToggle from './EditModeToggle.vue'
import MarkdownFilePane from './MarkdownFilePane.vue'
import { BRIEF_PATH, noteFiles } from './briefStatus'

const props = defineProps<{
  projectId: string
  /** 当前项目是否有一轮正在跑（同其他画布的 `busy`）。 */
  busy: boolean
}>()

type Tab = 'brief' | 'notes'
const tab = ref<Tab>('brief')
const mode = ref<'view' | 'edit'>('view')

const { data: fileTree } = useFileTreeQuery(() => props.projectId)
const { data: check, isError: checkFailed } = useTopicCheckQuery(() => props.projectId)

const filePaths = computed(() => fileTree.value?.files.map((f) => f.path) ?? [])
const notes = computed(() => noteFiles(filePaths.value))
// 简报文件还没写出来（或文件树还在加载）时不能进编辑模式：按钮按下后内容区仍是空提示。
const briefMissing = computed(() => !filePaths.value.includes(BRIEF_PATH))
const selectedNote = ref<string | null>(null)

// 默认选中第一份笔记；选中的笔记消失（回滚/删除）时回到第一份。
watch(
  notes,
  (list) => {
    if (list.length === 0) selectedNote.value = null
    else if (!list.some((n) => n.path === selectedNote.value)) selectedNote.value = list[0]!.path
  },
  { immediate: true },
)

// 换标签、换笔记：模式回到渲染，未保存的编辑不带到另一份文件上。
watch([tab, selectedNote], () => {
  mode.value = 'view'
})
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div
      class="flex flex-wrap items-center gap-1 text-sm"
      data-testid="topic-tabbar"
    >
      <button
        type="button"
        class="rounded px-3 py-1 whitespace-nowrap"
        :class="tab === 'brief' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        data-testid="tab-brief"
        @click="tab = 'brief'"
      >
        简报
      </button>
      <button
        type="button"
        class="rounded px-3 py-1 whitespace-nowrap"
        :class="tab === 'notes' ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
        data-testid="tab-notes"
        @click="tab = 'notes'"
      >
        笔记（{{ notes.length }}）
      </button>
      <div class="ml-auto flex items-center gap-2">
        <BriefStatusIcon
          :check="check"
          :failed="checkFailed"
        />
        <EditModeToggle
          v-if="tab === 'brief' || selectedNote"
          v-model:mode="mode"
          :busy="busy"
          :unavailable="tab === 'brief' && briefMissing"
        />
        <slot name="actions" />
      </div>
    </div>

    <MarkdownFilePane
      v-if="tab === 'brief'"
      v-model:mode="mode"
      :project-id="projectId"
      :path="BRIEF_PATH"
      stage="topic"
      :busy="busy"
      empty-hint="还没有 topic/brief.md。在左侧和 agent 对话，让它开始选题打磨。"
    />

    <div
      v-else
      class="grid min-h-0 flex-1 grid-cols-[minmax(0,12rem)_minmax(0,1fr)] gap-3"
    >
      <ul
        class="flex min-h-0 flex-col gap-1 overflow-y-auto text-sm"
        data-testid="notes-list"
      >
        <li
          v-if="notes.length === 0"
          class="text-muted-foreground text-xs"
        >
          还没有调研笔记。
        </li>
        <li
          v-for="note in notes"
          :key="note.path"
        >
          <button
            type="button"
            class="w-full truncate rounded px-2 py-1 text-left"
            :class="selectedNote === note.path ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
            :title="note.path"
            @click="selectedNote = note.path"
          >
            {{ note.label }}
          </button>
        </li>
      </ul>
      <MarkdownFilePane
        v-if="selectedNote"
        :key="selectedNote"
        v-model:mode="mode"
        :project-id="projectId"
        :path="selectedNote"
        stage="topic"
        :busy="busy"
        empty-hint="这份笔记已经不存在了。"
      />
      <p
        v-else
        class="text-muted-foreground text-sm"
      >
        从左侧选择一份笔记
      </p>
    </div>
  </div>
</template>
