<script setup lang="ts">
/** 风格的名称、分类、简介（都是 `STYLE.md` frontmatter 里的字段；改动由上层写回草稿）。 */
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { StyleMeta } from './styleFrontmatter'

defineProps<{ meta: StyleMeta; readonly?: boolean }>()
const emit = defineEmits<{ (e: 'update', patch: Partial<StyleMeta>): void }>()
</script>

<template>
  <div class="grid gap-3 md:grid-cols-[1fr_12rem]">
    <div class="flex flex-col gap-1.5">
      <Label for="style-name">名称</Label>
      <Input
        id="style-name"
        :model-value="meta.name"
        :disabled="readonly"
        data-testid="style-name"
        @update:model-value="emit('update', { name: String($event) })"
      />
    </div>
    <div class="flex flex-col gap-1.5">
      <Label for="style-category">分类</Label>
      <Input
        id="style-category"
        :model-value="meta.category"
        :disabled="readonly"
        placeholder="未分类"
        data-testid="style-category"
        @update:model-value="emit('update', { category: String($event) })"
      />
    </div>
    <div class="flex flex-col gap-1.5 md:col-span-2">
      <Label for="style-description">简介</Label>
      <Textarea
        id="style-description"
        :model-value="meta.description"
        :disabled="readonly"
        rows="2"
        class="min-h-0 resize-none"
        data-testid="style-description"
        @update:model-value="emit('update', { description: String($event) })"
      />
    </div>
  </div>
</template>
