<script setup lang="ts">
/**
 * 通用文件树（任务简报 T14，控制者裁定 1/4）：`.cache/`、`output/` 已经在
 * 后端 `GET /files` 里被过滤掉，这里只需要把 `upstream/` 下的条目（后端
 * 标记 `readonly: true`）单独分一组，置灰展示为"上游产物（只读）"。
 *
 * 平铺路径按目录组装成可折叠的树（`fileTree.ts`）：顶层目录首次出现时
 * 默认展开，更深的目录默认折叠；选中文件时自动展开它的祖先目录。
 */
import { computed, ref, watch } from 'vue'
import { ChevronRightIcon, FileIcon, FolderIcon, FolderOpenIcon } from '@lucide/vue'
import type { FileEntry } from '@/types/api'
import { ancestorDirs, buildFileTree, flattenVisible } from './fileTree'

const props = defineProps<{
  files: FileEntry[]
  selectedPath: string | null
}>()

const emit = defineEmits<{ (e: 'select', path: string): void }>()

const normalTree = computed(() => buildFileTree(props.files.filter((f) => !f.readonly)))
const upstreamTree = computed(() => buildFileTree(props.files.filter((f) => f.readonly)))

const expanded = ref(new Set<string>())
const seenTopDirs = new Set<string>()

watch(
  [normalTree, upstreamTree],
  ([normal, upstream]) => {
    const next = new Set(expanded.value)
    for (const node of [...normal, ...upstream]) {
      if (node.kind === 'dir' && !seenTopDirs.has(node.path)) {
        seenTopDirs.add(node.path)
        next.add(node.path)
      }
    }
    expanded.value = next
  },
  { immediate: true },
)

watch(
  () => props.selectedPath,
  (path) => {
    if (!path) return
    const missing = ancestorDirs(path).filter((dir) => !expanded.value.has(dir))
    if (missing.length > 0) expanded.value = new Set([...expanded.value, ...missing])
  },
  { immediate: true },
)

const normalRows = computed(() => flattenVisible(normalTree.value, expanded.value))
const upstreamRows = computed(() => flattenVisible(upstreamTree.value, expanded.value))

function toggle(path: string): void {
  const next = new Set(expanded.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  expanded.value = next
}

const groups = computed(() => [
  { key: 'normal', label: '文件', rows: normalRows.value, upstream: false },
  { key: 'upstream', label: 'upstream（只读）', rows: upstreamRows.value, upstream: true },
])
</script>

<template>
  <div class="flex min-h-0 flex-col gap-3 overflow-y-auto text-sm">
    <template
      v-for="group in groups"
      :key="group.key"
    >
      <div v-if="!group.upstream || group.rows.length > 0">
        <p class="text-muted-foreground mb-1 text-xs font-medium">
          {{ group.label }}
        </p>
        <ul>
          <li
            v-for="row in group.rows"
            :key="row.node.path"
          >
            <button
              v-if="row.node.kind === 'dir'"
              type="button"
              class="hover:bg-muted flex w-full items-center gap-1 rounded py-1 pr-2 text-left"
              :class="group.upstream ? 'text-muted-foreground italic' : ''"
              :style="{ paddingLeft: `${0.25 + row.depth * 0.75}rem` }"
              :title="row.node.path"
              :aria-expanded="expanded.has(row.node.path)"
              @click="toggle(row.node.path)"
            >
              <ChevronRightIcon
                class="size-3.5 shrink-0 transition-transform"
                :class="expanded.has(row.node.path) ? 'rotate-90' : ''"
              />
              <component
                :is="expanded.has(row.node.path) ? FolderOpenIcon : FolderIcon"
                class="text-muted-foreground size-3.5 shrink-0"
              />
              <span class="truncate">{{ row.node.name }}</span>
            </button>
            <button
              v-else
              type="button"
              class="flex w-full items-center gap-1 rounded py-1 pr-2 text-left"
              :class="[
                group.upstream ? 'text-muted-foreground italic' : '',
                row.node.path === selectedPath ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
              ]"
              :style="{ paddingLeft: `${1.125 + row.depth * 0.75}rem` }"
              :title="row.node.path"
              @click="emit('select', row.node.path)"
            >
              <FileIcon class="text-muted-foreground size-3.5 shrink-0" />
              <span class="truncate">{{ row.node.name }}</span>
            </button>
          </li>
          <li
            v-if="!group.upstream && group.rows.length === 0"
            class="text-muted-foreground px-2 py-1"
          >
            没有文件
          </li>
        </ul>
      </div>
    </template>
  </div>
</template>
