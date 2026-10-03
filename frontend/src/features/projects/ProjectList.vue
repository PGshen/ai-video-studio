<script setup lang="ts">
/**
 * 项目列表 + 新建对话框（任务简报 T13，控制者裁定 6）。创建成功后跳到
 * 新项目的选题阶段工作台。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import EffortSelect from '@/components/EffortSelect.vue'
import StyleSelect from '@/components/StyleSelect.vue'
import {
  useCreateProjectMutation,
  useProjectsQuery,
  useStylePresetsQuery,
} from '@/composables/queries'
import { DEFAULT_EFFORT, type Effort } from '@/composables/effortChoice'
import { initialStyleId, styleIdForRequest } from '@/composables/styleChoice'

const router = useRouter()
const { data: projects, isPending, isError } = useProjectsQuery()
const { data: stylePresets } = useStylePresetsQuery()

const dialogOpen = ref(false)
const title = ref('')
const styleId = ref('')
const effort = ref<Effort>(DEFAULT_EFFORT)
const createMutation = useCreateProjectMutation()

function openDialog(): void {
  title.value = ''
  styleId.value = initialStyleId(stylePresets.value ?? [])
  effort.value = DEFAULT_EFFORT
  createMutation.reset()
  dialogOpen.value = true
}

async function submit(): Promise<void> {
  const trimmed = title.value.trim()
  if (!trimmed) return
  const project = await createMutation.mutateAsync({
    title: trimmed,
    style_preset_id: styleIdForRequest(styleId.value),
    settings: { effort: effort.value },
  })
  dialogOpen.value = false
  await router.push(`/projects/${project.id}/topic`)
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex items-center justify-between">
      <h1 class="text-lg font-semibold">
        项目
      </h1>
      <Button @click="openDialog">
        新建项目
      </Button>
      <Dialog v-model:open="dialogOpen">
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
            <DialogDescription>给项目起个标题，创建后会进入选题阶段。</DialogDescription>
          </DialogHeader>
          <div class="flex flex-col gap-2">
            <Label for="project-title">标题</Label>
            <Input
              id="project-title"
              v-model="title"
              placeholder="例如：AI 视频工作台介绍"
              @keydown.enter="submit"
            />
            <StyleSelect
              id="project-style"
              v-model="styleId"
              class="mt-2"
              :presets="stylePresets ?? []"
            />
            <EffortSelect
              id="project-effort"
              v-model="effort"
              class="mt-2"
            />
            <p
              v-if="createMutation.isError.value"
              class="text-destructive text-sm"
            >
              创建失败：{{ (createMutation.error.value as Error)?.message }}
            </p>
          </div>
          <DialogFooter>
            <Button
              :disabled="!title.trim() || createMutation.isPending.value"
              @click="submit"
            >
              {{ createMutation.isPending.value ? '创建中…' : '创建' }}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>

    <p
      v-if="isPending"
      class="text-muted-foreground text-sm"
    >
      加载中…
    </p>
    <p
      v-else-if="isError"
      class="text-destructive text-sm"
    >
      项目列表加载失败。
    </p>
    <Card v-else-if="projects && projects.length === 0">
      <CardHeader>
        <CardTitle>还没有项目</CardTitle>
        <CardDescription>点击右上角「新建项目」开始。</CardDescription>
      </CardHeader>
    </Card>
    <div
      v-else
      class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
    >
      <Card
        v-for="project in projects"
        :key="project.id"
        class="cursor-pointer transition-colors hover:border-primary"
        @click="router.push(`/projects/${project.id}/${project.current_stage}`)"
      >
        <CardHeader>
          <CardTitle>{{ project.title }}</CardTitle>
          <CardDescription>当前阶段：{{ project.current_stage }}</CardDescription>
        </CardHeader>
      </Card>
    </div>
  </div>
</template>
