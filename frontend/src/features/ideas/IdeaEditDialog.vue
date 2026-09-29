<script setup lang="ts">
/**
 * 新建/编辑想法卡片的对话框（计划 M4 T9）。`idea` 为 `null` 是新建；`picked` 的卡片标题不可改
 * （后端也会拒绝）。表单状态和转换在 `ideaView.ts`，这里只管展示；提交由页面层调接口。
 */
import { ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { IdeaCreate, IdeaOut, IdeaScoreKey } from '@/types/api'
import {
  MAX_TAGS,
  SCORE_DIMENSIONS,
  draftFromIdea,
  draftToPayload,
  emptyDraft,
  parseTags,
  type IdeaDraft,
} from './ideaView'

const props = defineProps<{
  idea: IdeaOut | null
  pending?: boolean
  error?: string | null
}>()
const emit = defineEmits<{ (e: 'submit', payload: Required<IdeaCreate>): void }>()

const open = defineModel<boolean>('open', { default: false })
const draft = ref<IdeaDraft>(emptyDraft())

watch(open, (isOpen) => {
  if (isOpen) draft.value = props.idea ? draftFromIdea(props.idea) : emptyDraft()
})

function setScore(key: IdeaScoreKey, event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  const next = { ...draft.value.scores }
  if (value === '') delete next[key]
  else next[key] = Number(value)
  draft.value = { ...draft.value, scores: next }
}

function submit(): void {
  if (!draft.value.title.trim()) return
  emit('submit', draftToPayload(draft.value))
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{{ idea ? '编辑卡片' : '新建卡片' }}</DialogTitle>
        <DialogDescription>
          反直觉点写成「大家以为 X，实际是 Y」；评分 1–5，可以只评其中几项。
        </DialogDescription>
      </DialogHeader>

      <div class="flex flex-col gap-3">
        <div class="flex flex-col gap-1.5">
          <Label for="idea-title">标题</Label>
          <Input
            id="idea-title"
            v-model="draft.title"
            :disabled="idea?.status === 'picked'"
            placeholder="简短具体的选题标题"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="idea-pitch">一句话卖点</Label>
          <Textarea
            id="idea-pitch"
            v-model="draft.pitch"
            rows="2"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="idea-counter">反直觉点</Label>
          <Textarea
            id="idea-counter"
            v-model="draft.counterintuitive"
            rows="2"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label for="idea-tags">标签（逗号或顿号分隔，最多 {{ MAX_TAGS }} 个）</Label>
          <Input
            id="idea-tags"
            v-model="draft.tags"
          />
          <p
            v-if="parseTags(draft.tags).length > MAX_TAGS"
            class="text-destructive text-xs"
          >
            标签最多 {{ MAX_TAGS }} 个
          </p>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div
            v-for="dim in SCORE_DIMENSIONS"
            :key="dim.key"
            class="flex flex-col gap-1.5"
          >
            <Label :for="`idea-score-${dim.key}`">{{ dim.label }}</Label>
            <select
              :id="`idea-score-${dim.key}`"
              class="border-input bg-background h-9 rounded-md border px-2 text-sm"
              :value="draft.scores[dim.key] ?? ''"
              @change="setScore(dim.key, $event)"
            >
              <option value="">
                未评
              </option>
              <option
                v-for="n in 5"
                :key="n"
                :value="n"
              >
                {{ n }}
              </option>
            </select>
          </div>
        </div>
        <p
          v-if="error"
          class="text-destructive text-sm"
        >
          {{ error }}
        </p>
      </div>

      <DialogFooter>
        <Button
          :disabled="
            !draft.title.trim() || pending || parseTags(draft.tags).length > MAX_TAGS
          "
          @click="submit"
        >
          {{ pending ? '保存中…' : '保存' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
