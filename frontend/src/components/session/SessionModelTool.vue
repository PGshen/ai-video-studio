<script setup lang="ts">
/**
 * 输入框工具栏里的换模型下拉（头脑风暴、风格对话用；项目工作台自己在页面里拼同样的东西）：
 * 按会话 id 从该范围的会话列表里找出当前会话，没有会话时什么都不显示。
 */
import { computed } from 'vue'
import { useModelProfilesQuery, useSessionsQuery } from '@/composables/queries'
import type { SessionScope } from '@/composables/sessionScope'
import ModelSwitcher from './ModelSwitcher.vue'

const props = defineProps<{
  scope: SessionScope
  sessionId: string | null
}>()

const { data: profiles } = useModelProfilesQuery()
const { data: sessions } = useSessionsQuery(() => props.scope)
const currentSession = computed(() => sessions.value?.find((s) => s.id === props.sessionId))
</script>

<template>
  <ModelSwitcher
    v-if="currentSession && profiles"
    :key="currentSession.id"
    :session="currentSession"
    :profiles="profiles"
    :scope="scope"
    compact
  />
</template>
