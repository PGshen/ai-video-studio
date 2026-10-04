<script setup lang="ts">
/**
 * 带二次确认的删除按钮：点按钮先弹确认框，确认后执行 `action`。`action` 失败（比如 409
 * 「有关联项目」）时确认框保持打开并显示后端给的原因。`compact` 时只显示垃圾桶图标（卡片右上角）。
 */
import { ref } from 'vue'
import { Trash2 } from '@lucide/vue'
import { errorMessage } from '@/api/http'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'

const props = defineProps<{
  title: string
  description: string
  testId: string
  /** 确认后执行的删除；reject 时在确认框里显示错误。 */
  action: () => Promise<unknown>
  compact?: boolean
  disabled?: boolean
}>()

const open = ref(false)
const pending = ref(false)
const error = ref<string | null>(null)

function ask(): void {
  error.value = null
  open.value = true
}

async function confirm(): Promise<void> {
  pending.value = true
  error.value = null
  try {
    await props.action()
    open.value = false
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <Button
    v-if="compact"
    size="icon-xs"
    variant="ghost"
    class="hover:text-destructive"
    title="删除"
    aria-label="删除"
    :data-testid="testId"
    :disabled="disabled"
    @click="ask"
  >
    <Trash2 />
  </Button>
  <Button
    v-else
    size="sm"
    variant="ghost"
    class="text-destructive hover:text-destructive"
    :data-testid="testId"
    :disabled="disabled"
    @click="ask"
  >
    删除
  </Button>

  <AlertDialog v-model:open="open">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{{ title }}</AlertDialogTitle>
        <AlertDialogDescription>{{ description }}</AlertDialogDescription>
      </AlertDialogHeader>
      <p
        v-if="error"
        class="text-destructive text-sm"
      >
        {{ error }}
      </p>
      <AlertDialogFooter>
        <AlertDialogCancel :disabled="pending">
          取消
        </AlertDialogCancel>
        <!-- 不用 AlertDialogAction：它点击后一定会关闭对话框，失败时就看不到原因了。 -->
        <Button
          variant="destructive"
          :disabled="pending"
          @click="confirm"
        >
          确认删除
        </Button>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>
