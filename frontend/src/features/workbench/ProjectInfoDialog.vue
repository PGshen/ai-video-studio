<script setup lang="ts">
/** 项目「信息」对话框（只读）：正文见 `ProjectInfoBody`，打开时才挂载并请求数据。 */
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import ProjectInfoBody from './ProjectInfoBody.vue'

defineProps<{ projectId: string }>()
const open = defineModel<boolean>('open', { default: false })
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>项目信息</DialogTitle>
        <DialogDescription>
          这个项目的来源：关联的选题条目，以及使用的风格。
        </DialogDescription>
      </DialogHeader>
      <ProjectInfoBody :project-id="projectId" />
    </DialogContent>
  </Dialog>
</template>
