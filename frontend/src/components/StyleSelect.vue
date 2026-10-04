<script setup lang="ts">
/**
 * 创建项目时的风格选择器（计划 M5 T11）：项目页的新建对话框和选题池的「创建项目」对话框共用。
 * 值是风格 id，空字符串表示「不指定」（服务端用默认风格，没有默认风格时用占位）；预选默认风格由
 * 调用方用 `composables/styleChoice.ts::initialStyleId` 设置。风格库里没有任何风格时只显示一行说明。
 */
import { computed } from 'vue'
import { Label } from '@/components/ui/label'
import { styleSelectOptions } from '@/composables/styleChoice'
import type { StyleSummaryOut } from '@/types/api'

const props = defineProps<{
  presets: StyleSummaryOut[]
  /** 给 `<select>` 和 `<label>` 用的 id，同一页面有多个选择器时要不同。 */
  id: string
}>()
const value = defineModel<string>({ default: '' })

const options = computed(() => styleSelectOptions(props.presets))
const selected = computed(() => props.presets.find((p) => p.id === value.value))
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <Label :for="id">风格</Label>
    <p
      v-if="presets.length === 0"
      class="text-muted-foreground text-xs"
      data-testid="style-empty"
    >
      风格库里还没有风格，将使用占位风格。可以到「风格库」新建，或导入旧项目的风格。
    </p>
    <template v-else>
      <select
        :id="id"
        v-model="value"
        class="border-input bg-background h-9 rounded-md border px-2 text-sm"
        data-testid="style-select"
      >
        <option
          v-for="option in options"
          :key="option.value"
          :value="option.value"
        >
          {{ option.label }}
        </option>
      </select>
      <p
        v-if="selected?.description"
        class="text-muted-foreground line-clamp-2 text-xs"
      >
        {{ selected.description }}
      </p>
    </template>
  </div>
</template>
