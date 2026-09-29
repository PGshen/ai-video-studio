<script setup lang="ts">
/**
 * 「创建项目」对话框（计划 M4 T9）：标题预填卡片标题，可以改；成功后跳到新项目的选题阶段。
 * 创建成功后 `useCreateProjectMutation` 会让选题池和项目列表的查询失效（卡片变成 `picked`）。
 */
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
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
import { useCreateProjectMutation } from '@/composables/queries'
import type { IdeaOut } from '@/types/api'

const props = defineProps<{ idea: IdeaOut | null }>()
const open = defineModel<boolean>('open', { default: false })

const router = useRouter()
const mutation = useCreateProjectMutation()
const title = ref('')

watch(open, (isOpen) => {
  if (isOpen) {
    title.value = props.idea?.title ?? ''
    mutation.reset()
  }
})

async function submit(): Promise<void> {
  const trimmed = title.value.trim()
  if (!trimmed || !props.idea) return
  const project = await mutation.mutateAsync({ title: trimmed, idea_id: props.idea.id })
  open.value = false
  await router.push(`/projects/${project.id}/topic`)
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>用这张卡片创建项目</DialogTitle>
        <DialogDescription>
          项目会进入选题打磨阶段，卡片内容会作为起点带过去；卡片随后变为「已创建项目」。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-2">
        <Label for="create-project-title">项目标题</Label>
        <Input
          id="create-project-title"
          v-model="title"
          @keydown.enter="submit"
        />
        <p
          v-if="mutation.isError.value"
          class="text-destructive text-sm"
        >
          创建失败：{{ (mutation.error.value as Error)?.message }}
        </p>
      </div>
      <DialogFooter>
        <Button
          :disabled="!title.trim() || mutation.isPending.value"
          @click="submit"
        >
          {{ mutation.isPending.value ? '创建中…' : '创建项目' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
