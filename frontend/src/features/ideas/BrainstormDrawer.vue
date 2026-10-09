<script setup lang="ts">
/**
 * 头脑风暴抽屉（计划 M4 T10）：选题池页右侧的对话面板，和没有项目的头脑风暴会话对话。
 * 做成停靠在页面右侧的非模态面板，而不是遮罩式的 Sheet——agent 新建卡片时，左边的卡片网格
 * 要能实时看到变化（`useSessionStream` 在 `create_idea`/`update_idea` 结果到达时让选题池查询失效）。
 * 会话切换（气泡菜单）、消息流和输入框里的换模型复用 `components/session/`（和项目工作台同一套组件，范围不同）。
 */
import { ref } from 'vue'
import SessionPanel from '@/components/session/SessionPanel.vue'
import SessionModelTool from '@/components/session/SessionModelTool.vue'
import SessionSwitcher from '@/components/session/SessionSwitcher.vue'
import { useEnsureSession } from '@/components/session/useEnsureSession'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { brainstormScope } from '@/composables/sessionScope'

const emit = defineEmits<{ (e: 'close'): void }>()
const sessionId = ref<string | null>(null)
const createSession = useEnsureSession(ref(brainstormScope), sessionId)
</script>

<template>
  <Card
    class="flex min-h-0 flex-col"
    data-testid="brainstorm-drawer"
  >
    <CardHeader class="flex flex-row items-center justify-between gap-2">
      <CardTitle>头脑风暴</CardTitle>
      <Button
        size="sm"
        variant="ghost"
        @click="emit('close')"
      >
        收起
      </Button>
    </CardHeader>
    <CardContent class="flex min-h-0 flex-1 flex-col gap-2">
      <SessionSwitcher
        v-model:session-id="sessionId"
        :scope="brainstormScope"
      />
      <SessionPanel
        :session-id="sessionId"
        :project-id="null"
        :create-session="createSession"
        attachment-accept="images"
      >
        <template #tools>
          <SessionModelTool
            :scope="brainstormScope"
            :session-id="sessionId"
          />
        </template>
      </SessionPanel>
    </CardContent>
  </Card>
</template>
