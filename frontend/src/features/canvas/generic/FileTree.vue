<script setup lang="ts">
/**
 * 通用文件树（任务简报 T14，控制者裁定 1/4）：`.cache/`、`output/` 已经在
 * 后端 `GET /files` 里被过滤掉，这里只需要把 `upstream/` 下的条目（后端
 * 标记 `readonly: true`）单独分一组，置灰展示为"上游产物（只读）"。
 */
import { computed } from 'vue'
import type { FileEntry } from '@/types/api'

const props = defineProps<{
  files: FileEntry[]
  selectedPath: string | null
}>()

const emit = defineEmits<{ (e: 'select', path: string): void }>()

const normalFiles = computed(() => props.files.filter((f) => !f.readonly))
const upstreamFiles = computed(() => props.files.filter((f) => f.readonly))
</script>

<template>
  <div class="flex min-h-0 flex-col gap-3 overflow-y-auto text-sm">
    <div>
      <p class="text-muted-foreground mb-1 text-xs font-medium">
        文件
      </p>
      <ul>
        <li
          v-for="file in normalFiles"
          :key="file.path"
        >
          <button
            type="button"
            class="w-full truncate rounded px-2 py-1 text-left"
            :class="
              file.path === selectedPath
                ? 'bg-primary/10 text-primary'
                : 'hover:bg-muted'
            "
            @click="emit('select', file.path)"
          >
            {{ file.path }}
          </button>
        </li>
        <li
          v-if="normalFiles.length === 0"
          class="text-muted-foreground px-2 py-1"
        >
          没有文件
        </li>
      </ul>
    </div>

    <div v-if="upstreamFiles.length > 0">
      <p class="text-muted-foreground mb-1 text-xs font-medium">
        upstream（只读）
      </p>
      <ul>
        <li
          v-for="file in upstreamFiles"
          :key="file.path"
        >
          <button
            type="button"
            class="text-muted-foreground w-full truncate rounded px-2 py-1 text-left italic"
            :class="file.path === selectedPath ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
            @click="emit('select', file.path)"
          >
            {{ file.path }}
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
