<script setup lang="ts">
/**
 * 风格目录的文件树：入口 `STYLE.md`、`references/`（引用文件）、`exemplars/`（金样本）三组。
 * 可编辑时每组有「添加」（行内输入文件名，规则见 `styleFiles.ts`）和删除按钮；入口文件不能删除。
 */
import { Plus, X } from '@lucide/vue'
import { computed, nextTick, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { ENTRY_FILE, fileNameProblem, groupFiles, type StyleDirectory } from './styleFiles'

const props = defineProps<{ files: readonly string[]; readonly?: boolean }>()
const active = defineModel<string>('active', { required: true })
const emit = defineEmits<{
  (e: 'add', directory: StyleDirectory, name: string): void
  (e: 'remove', path: string): void
}>()

const groups = computed(() => groupFiles(props.files))
const sections = computed(() => [
  { directory: 'references' as const, label: '引用文件', paths: groups.value.references },
  { directory: 'exemplars' as const, label: '金样本', paths: groups.value.exemplars },
])

const adding = ref<StyleDirectory | null>(null)
const newName = ref('')
const problem = ref<string | null>(null)
const nameInput = ref<InstanceType<typeof Input> | null>(null)

async function startAdd(directory: StyleDirectory): Promise<void> {
  adding.value = directory
  newName.value = ''
  problem.value = null
  await nextTick()
  const el = (nameInput.value as { $el?: HTMLElement } | null)?.$el
  el?.focus()
}

function cancelAdd(): void {
  adding.value = null
  problem.value = null
}

function submitAdd(): void {
  if (adding.value === null) return
  const issue = fileNameProblem(adding.value, newName.value, props.files)
  if (issue !== null) {
    problem.value = issue
    return
  }
  emit('add', adding.value, newName.value.trim())
  cancelAdd()
}

const baseName = (path: string) => path.slice(path.indexOf('/') + 1)
const itemClass = (path: string) =>
  cn(
    'hover:bg-accent flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm',
    active.value === path && 'bg-accent font-medium',
  )
</script>

<template>
  <div class="flex flex-col gap-3 text-sm">
    <button
      v-if="groups.hasEntry"
      type="button"
      :class="itemClass(ENTRY_FILE)"
      :aria-current="active === ENTRY_FILE ? 'true' : undefined"
      data-testid="file-STYLE.md"
      @click="active = ENTRY_FILE"
    >
      STYLE.md（入口）
    </button>

    <section
      v-for="section in sections"
      :key="section.directory"
      class="flex flex-col gap-1"
      :data-testid="`group-${section.directory}`"
    >
      <div class="text-muted-foreground flex items-center justify-between px-2 text-xs">
        <span>{{ section.label }}（{{ section.paths.length }}）</span>
        <Button
          v-if="!readonly"
          size="xs"
          variant="ghost"
          :data-testid="`add-${section.directory}`"
          @click="startAdd(section.directory)"
        >
          <Plus />添加
        </Button>
      </div>

      <div
        v-for="path in section.paths"
        :key="path"
        class="flex items-center gap-1"
      >
        <button
          type="button"
          :class="itemClass(path)"
          :aria-current="active === path ? 'true' : undefined"
          :data-testid="`file-${path}`"
          @click="active = path"
        >
          {{ baseName(path) }}
        </button>
        <Button
          v-if="!readonly"
          size="icon-xs"
          variant="ghost"
          class="hover:text-destructive"
          :aria-label="`删除 ${path}`"
          :data-testid="`delete-${path}`"
          @click="emit('remove', path)"
        >
          <X />
        </Button>
      </div>

      <div
        v-if="adding === section.directory"
        class="flex flex-col gap-1 px-1"
      >
        <Input
          ref="nameInput"
          v-model="newName"
          :placeholder="section.directory === 'references' ? 'color-scheme.md' : 'exemplar-2.json'"
          data-testid="new-file-name"
          @keydown.enter.prevent="submitAdd"
          @keydown.esc.prevent="cancelAdd"
        />
        <p
          v-if="problem"
          class="text-destructive text-xs"
          data-testid="file-name-error"
        >
          {{ problem }}
        </p>
      </div>
    </section>
  </div>
</template>
