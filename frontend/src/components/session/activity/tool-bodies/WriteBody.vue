<script setup lang="ts">
/** `write`：写入的内容（`Write`）、新旧差异（`Edit`/`MultiEdit`）或补丁（`apply_patch`）。 */
import { computed } from 'vue'
import type { ToolCallItem } from '@/composables/useSessionStream'
import { codeLanguage } from '@/components/session/codeLanguage'
import type { ToolView } from '@/components/session/toolPresentation'
import CodeView from '@/components/session/activity/CodeView.vue'
import DiffView from '@/components/session/activity/DiffView.vue'
import ErrorPane from '@/components/session/activity/ErrorPane.vue'
import ToolPane from '@/components/session/activity/ToolPane.vue'
import GenericBody from './GenericBody.vue'

const props = defineProps<{ item: ToolCallItem; view: ToolView; projectId: string | null }>()

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null)

function replacement(old: unknown, next: unknown): string | null {
  const before = text(old)
  const after = text(next)
  if (before === null || after === null) return null
  const lines = (body: string, mark: string) => (body === '' ? [] : body.split('\n').map((l) => mark + l))
  return [...lines(before, '-'), ...lines(after, '+')].join('\n')
}

/** 把请求整理成 `content`（整文件内容）或 `diff`（差异文本）；认不出就是 `null`，走通用正文。 */
const request = computed<{ content: string } | { diff: string } | null>(() => {
  const { args, name } = props.item
  if (name === 'Write' || name === 'write_file') {
    const content = text(args.content)
    return content === null ? null : { content }
  }
  if (name === 'Edit') {
    const diff = replacement(args.old_string, args.new_string)
    return diff === null ? null : { diff }
  }
  if (name === 'edit_file') {
    const diff = replacement(args.old_text, args.new_text)
    return diff === null ? null : { diff }
  }
  if (name === 'MultiEdit' && Array.isArray(args.edits)) {
    const hunks = (args.edits as Record<string, unknown>[])
      .map((edit) => replacement(edit?.old_string, edit?.new_string))
      .filter((hunk): hunk is string => hunk !== null)
    return hunks.length === 0 ? null : { diff: hunks.join('\n@@\n') }
  }
  if (name === 'apply_patch') {
    const diff = text(args.diff)
    return diff === null ? null : { diff }
  }
  return null
})

const title = computed(() => props.view.path ?? props.view.summary)
const language = computed(() => codeLanguage(props.view.path))
const status = computed(() =>
  props.item.result && !props.item.result.isError ? props.item.result.text : '',
)
</script>

<template>
  <GenericBody
    v-if="request === null"
    :item="item"
    :project-id="projectId"
  />
  <div
    v-else
    class="space-y-2"
  >
    <ToolPane
      v-if="'content' in request"
      :title="title"
      :language="language"
      :copy-text="request.content"
    >
      <CodeView
        :code="request.content"
        :language="language"
        line-numbers
      />
    </ToolPane>
    <ToolPane
      v-else
      :title="title"
      language="diff"
      :copy-text="request.diff"
    >
      <DiffView :text="request.diff" />
    </ToolPane>
    <p
      v-if="status"
      class="text-muted-foreground text-xs"
    >
      {{ status }}
    </p>
    <ErrorPane :item="item" />
  </div>
</template>
