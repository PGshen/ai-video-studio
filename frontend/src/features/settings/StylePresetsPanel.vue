<script setup lang="ts">
/**
 * 「风格库」子页（计划 M5 T11）：左边按分类分组的风格列表，右边编辑器。风格是 skill 形态的目录
 * （入口 `STYLE.md` + `references/` + `exemplars/`，ADR 0011），创建项目时复制进项目。
 * 旧项目的风格用命令行导入（`make import-legacy-styles`），这里不提供导入界面。
 */
import { ref } from 'vue'
import { errorMessage } from '@/api/http'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useStylePresetsQuery } from '@/composables/queries'
import StylePresetEditor from './StylePresetEditor.vue'
import { groupByCategory } from './styleDraft'

const { data: presets, isPending, error: loadError } = useStylePresetsQuery()

/** `null`：没有选中任何风格；`'new'`：新建草稿；否则是预设 id。 */
const selected = ref<string | 'new' | null>(null)
const editorDirty = ref(false)

function select(target: string | 'new'): void {
  if (target === selected.value) return
  if (editorDirty.value && !window.confirm('当前风格有未保存的修改，切换会丢掉它们。继续吗？')) return
  editorDirty.value = false
  selected.value = target
}

function onSaved(id: string): void {
  editorDirty.value = false
  selected.value = id
}

function onDeleted(): void {
  editorDirty.value = false
  selected.value = null
}

function onDuplicated(id: string): void {
  editorDirty.value = false
  selected.value = id
}
</script>

<template>
  <section class="flex flex-col gap-4">
    <div>
      <h2 class="text-lg font-medium">
        风格库
      </h2>
      <p class="text-muted-foreground text-sm">
        一套风格是一个目录：入口 STYLE.md 说明各文件什么时候读，references/ 放叙事蓝图、配色、动画风格，
        exemplars/ 放金样本。创建项目时选一套复制进项目。
      </p>
    </div>

    <p
      v-if="isPending"
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

    <div
      v-else
      class="flex gap-4"
    >
      <aside class="flex w-64 shrink-0 flex-col gap-3">
        <Button
          data-testid="new-style"
          @click="select('new')"
        >
          新建风格
        </Button>

        <p
          v-if="(presets ?? []).length === 0"
          class="text-muted-foreground text-sm"
          data-testid="styles-empty"
        >
          风格库还是空的。新建一套，或用 make import-legacy-styles 导入旧项目的风格。
        </p>

        <div
          v-for="group in groupByCategory(presets ?? [])"
          :key="group.category"
          class="flex flex-col gap-1"
        >
          <div class="text-muted-foreground px-2 text-xs">
            {{ group.category }}
          </div>
          <button
            v-for="preset in group.items"
            :key="preset.id"
            type="button"
            class="hover:bg-muted flex flex-col gap-0.5 rounded-md border px-3 py-2 text-left text-sm"
            :class="{ 'border-primary': selected === preset.id }"
            :data-testid="`style-${preset.name}`"
            @click="select(preset.id)"
          >
            <span class="flex items-center justify-between gap-2">
              <span class="font-medium">{{ preset.name }}</span>
              <Badge
                v-if="preset.is_default"
                variant="secondary"
              >
                默认
              </Badge>
            </span>
            <span class="text-muted-foreground text-xs">
              {{ preset.reference_count }} 个引用 · {{ preset.exemplar_count }} 个金样本
            </span>
          </button>
        </div>
      </aside>

      <StylePresetEditor
        v-if="selected !== null"
        :key="selected"
        :preset-id="selected === 'new' ? null : selected"
        @saved="onSaved"
        @deleted="onDeleted"
        @duplicated="onDuplicated"
        @dirty="editorDirty = $event"
      />
      <p
        v-else
        class="text-muted-foreground text-sm"
      >
        从左边选一套风格，或新建一套。
      </p>
    </div>
  </section>
</template>
