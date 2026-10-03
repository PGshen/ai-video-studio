<script setup lang="ts">
/**
 * 项目「思考强度」选择器：创建项目的两个对话框和项目设置对话框共用。选项和默认值见
 * `composables/effortChoice.ts`。
 */
import { computed } from 'vue'
import { Label } from '@/components/ui/label'
import { DEFAULT_EFFORT, EFFORT_OPTIONS, type Effort } from '@/composables/effortChoice'

defineProps<{
  /** 给 `<select>` 和 `<label>` 用的 id，同一页面有多个选择器时要不同。 */
  id: string
  disabled?: boolean
}>()
const value = defineModel<Effort>({ default: DEFAULT_EFFORT })

const hint = computed(() => EFFORT_OPTIONS.find((option) => option.value === value.value)?.hint)
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <Label :for="id">思考强度</Label>
    <select
      :id="id"
      v-model="value"
      class="border-input bg-background h-9 rounded-md border px-2 text-sm disabled:opacity-60"
      :disabled="disabled"
      data-testid="effort-select"
    >
      <option
        v-for="option in EFFORT_OPTIONS"
        :key="option.value"
        :value="option.value"
      >
        {{ option.label }}
      </option>
    </select>
    <p
      v-if="hint"
      class="text-muted-foreground text-xs"
      data-testid="effort-hint"
    >
      {{ hint }}
    </p>
  </div>
</template>
