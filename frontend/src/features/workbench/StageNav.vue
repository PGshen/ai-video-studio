<script setup lang="ts">
/**
 * 阶段导航条 + 当前阶段的 [定稿]/[重新打开]（任务简报 T13，控制者裁定 5）。
 * 样式/可点性映射交给纯函数 `stageStatusStyle`（见同目录 spec），这里只
 * 负责渲染和路由跳转、发起 finalize/reopen mutation。
 */
import { CircleAlert, Settings, SquareCheckBig, Undo2 } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import RailGroup from '@/components/RailGroup.vue'
import { Button } from '@/components/ui/button'
import {
  useFinalizeStageMutation,
  useReopenStageMutation,
  useSuggestionSummaryQuery,
} from '@/composables/queries'
import { badgeCount } from '@/components/session/suggestionFlow'
import type { StageOut } from '@/types/api'
import { ApiError } from '@/api/http'
import ProjectSettingsDialog from './ProjectSettingsDialog.vue'
import { stageStatusStyle } from './stageStatus'

const props = defineProps<{
  projectId: string
  stages: StageOut[]
  currentStage: string
  /** 竖栏折叠：只显示图标，名称和说明放进悬停提示。 */
  collapsed?: boolean
}>()

const STAGE_TITLES: Record<string, string> = {
  topic: '选题',
  narrative: '叙事',
  animation: '动画',
}

const router = useRouter()

const currentStageInfo = computed(() => props.stages.find((s) => s.stage === props.currentStage))

/** 阶段按钮上的角标：下游提给该阶段、还没处理的回退建议数量（M5 T13）。 */
const { data: suggestionSummary } = useSuggestionSummaryQuery(() => props.projectId)

const finalizeMutation = useFinalizeStageMutation(() => props.projectId)
const reopenMutation = useReopenStageMutation(() => props.projectId)
const actionError = computed(() => {
  if (finalizeMutation.isError.value) return `定稿失败：${errorDetail(finalizeMutation.error.value)}`
  if (reopenMutation.isError.value) return `重新打开失败：${errorDetail(reopenMutation.error.value)}`
  return null
})
const finalizeDialogOpen = ref(false)
const settingsDialogOpen = ref(false)

function goToStage(stage: StageOut): void {
  if (stageStatusStyle(stage.status).disabled) return
  void router.push(`/projects/${props.projectId}/${stage.stage}`)
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === 'string' ? error.detail : error.message
  }
  return error instanceof Error ? error.message : '未知错误'
}

async function confirmFinalize(): Promise<void> {
  try {
    await finalizeMutation.mutateAsync(props.currentStage)
  } catch {
    // 被拒绝（例如选题简报没通过 `check_brief`，409）：错误显示在导航条上，见模板。
  } finally {
    finalizeDialogOpen.value = false
  }
}
</script>

<template>
  <!-- 工作台左侧竖栏的上半部分：阶段进度（选题 → 叙事 → 动画）+ 项目设置 / 重新打开 / 定稿。
       折叠时只剩图标；窄屏横向排列。外框和折叠按钮由 ProjectWorkbenchPage 的竖栏负责。 -->
  <div class="flex flex-col gap-3">
    <RailGroup
      title="进度"
      :collapsed="collapsed"
    >
      <nav
        class="flex flex-row flex-wrap gap-1 text-sm lg:flex-col"
        :class="collapsed ? 'lg:items-center' : ''"
        aria-label="阶段"
      >
        <button
          v-for="(stage, index) in stages"
          :key="stage.stage"
          type="button"
          :class="[
            stageStatusStyle(stage.status).className,
            'relative flex items-center gap-2 rounded-md text-left whitespace-nowrap',
            collapsed ? 'p-1' : 'px-2 py-1.5',
            stage.stage === currentStage ? 'bg-muted' : 'hover:bg-muted/60',
          ]"
          :title="`${STAGE_TITLES[stage.stage] ?? stage.stage}${stageStatusStyle(stage.status).suffix}`"
          :aria-current="stage.stage === currentStage ? 'step' : undefined"
          :disabled="stageStatusStyle(stage.status).disabled"
          @click="goToStage(stage)"
        >
          <span
            class="flex size-5 shrink-0 items-center justify-center rounded-full border text-xs"
            :class="stage.stage === currentStage ? 'border-primary bg-primary text-primary-foreground' : ''"
          >{{ index + 1 }}</span>
          <span v-if="!collapsed">{{ STAGE_TITLES[stage.stage] ?? stage.stage }}{{ stageStatusStyle(stage.status).suffix }}</span>
          <span
            v-if="badgeCount(suggestionSummary, stage.stage) > 0"
            :class="
              collapsed
                ? 'absolute -top-0.5 -right-0.5 size-2 rounded-full bg-sky-600'
                : 'ml-auto rounded-full bg-sky-600 px-1.5 text-xs text-white'
            "
            :title="`${badgeCount(suggestionSummary, stage.stage)} 条待处理的回退建议`"
            :data-testid="`suggestion-badge-${stage.stage}`"
          >{{ collapsed ? '' : badgeCount(suggestionSummary, stage.stage) }}</span>
        </button>
      </nav>
    </RailGroup>

    <RailGroup
      v-if="currentStageInfo"
      title="操作"
      :collapsed="collapsed"
    >
      <div
        class="flex flex-col gap-2 max-lg:flex-row max-lg:flex-wrap max-lg:items-center"
        :class="collapsed ? 'lg:items-center' : ''"
      >
        <p
          v-if="actionError && !collapsed"
          class="text-destructive text-xs"
        >
          {{ actionError }}
        </p>
        <CircleAlert
          v-else-if="actionError"
          class="text-destructive size-4"
          :title="actionError"
        />
        <!-- 三个操作样式一致：无边框按钮 + 图标 + 左对齐；折叠时只剩图标。 -->
        <Button
          variant="ghost"
          :size="collapsed ? 'icon-sm' : 'sm'"
          :class="collapsed ? '' : 'w-full justify-start'"
          title="项目设置"
          data-testid="open-project-settings"
          @click="settingsDialogOpen = true"
        >
          <Settings />
          <span v-if="!collapsed">项目设置</span>
        </Button>
        <Button
          v-if="currentStageInfo.status === 'finalized' || currentStageInfo.status === 'stale'"
          variant="ghost"
          :size="collapsed ? 'icon-sm' : 'sm'"
          :class="collapsed ? '' : 'w-full justify-start'"
          title="重新打开"
          :disabled="reopenMutation.isPending.value"
          @click="reopenMutation.mutate(currentStage)"
        >
          <Undo2 />
          <span v-if="!collapsed">重新打开</span>
        </Button>
        <Button
          v-if="currentStageInfo.status === 'active' || currentStageInfo.status === 'stale'"
          variant="ghost"
          :size="collapsed ? 'icon-sm' : 'sm'"
          :class="collapsed ? '' : 'w-full justify-start'"
          title="定稿"
          :disabled="finalizeMutation.isPending.value"
          @click="finalizeDialogOpen = true"
        >
          <SquareCheckBig />
          <span v-if="!collapsed">定稿</span>
        </Button>
      </div>
    </RailGroup>

    <ProjectSettingsDialog
      v-model:open="settingsDialogOpen"
      :project-id="projectId"
    />

    <AlertDialog v-model:open="finalizeDialogOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>确认定稿？</AlertDialogTitle>
          <AlertDialogDescription>
            定稿后这个阶段会被标记为已完成，下游阶段可以基于当前快照继续；仍然可以之后重新打开。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction @click="confirmFinalize">
            确认定稿
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
