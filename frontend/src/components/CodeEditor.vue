<script setup lang="ts">
/**
 * CodeMirror 6 的小型封装（任务简报 T14，控制者裁定 2；T12 从
 * `features/canvas/generic/CodeEditor.vue` 挪到这里，决策记录 D36——
 * `animation` 画布要复用它，但 ESLint 的 `features/* 之间互不 import`
 * 规则不允许跨阶段画布互相 import，挪进 `components/` 后两边都能用）。
 * 不用 `vue-codemirror`，只用「依赖清单」里允许的四个包——`codemirror`
 * （重新导出 `EditorView`/`basicSetup`）、`@codemirror/lang-{markdown,
 * json,python}`。`codemirror` 包**不**重新导出 `EditorState`/
 * `Compartment`，所以这里没法用 compartment 动态重新配置扩展；改用更简单
 * 但足够用的办法——`language`/`readonly` 变化时整个销毁重建
 * `EditorView`（这两者只在切换文件/切换 agent 运行状态时变化，频率很低，
 * 重建的代价可以接受）。`content` 变化时先比较当前文档内容，只有真正来自
 * 外部（切换文件、[载入最新]）才重建；用户敲字触发的 `update:content`
 * 事件被父组件原样传回来时字符串相等，不会形成"敲一个字重建一次"的死循环。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorView, basicSetup } from 'codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { json } from '@codemirror/lang-json'
import { python } from '@codemirror/lang-python'
import type { EditorLanguage } from './codeEditorLanguage'

// `codemirror` 包不重新导出 `Extension` 类型（只导出 `EditorView`/
// `basicSetup`/`minimalSetup`），直接 `import type ... from '@codemirror/
// state'` 在 pnpm 严格 node_modules 下解析不到（它只是 `codemirror` 的
// 间接依赖，不在「依赖清单」允许的包里）。用 `typeof basicSetup` 派生同一
// 个类型，不需要显式导入。
type Extension = typeof basicSetup

const props = defineProps<{
  content: string
  language: EditorLanguage
  readonly: boolean
}>()

const emit = defineEmits<{ (e: 'update:content', value: string): void }>()

const container = ref<HTMLDivElement | null>(null)
let view: EditorView | null = null

function languageExtensions(): Extension[] {
  switch (props.language) {
    case 'markdown':
      return [markdown()]
    case 'json':
      return [json()]
    case 'python':
      return [python()]
    default:
      return []
  }
}

function createView(doc: string): void {
  view?.destroy()
  if (!container.value) return
  view = new EditorView({
    doc,
    parent: container.value,
    extensions: [
      basicSetup,
      ...languageExtensions(),
      EditorView.editable.of(!props.readonly),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) emit('update:content', update.state.doc.toString())
      }),
    ],
  })
}

onMounted(() => createView(props.content))
onBeforeUnmount(() => view?.destroy())

// 只读态或语言变化：重建（见上方注释，`codemirror` 包没暴露 Compartment）。
watch([() => props.readonly, () => props.language], () => {
  createView(view?.state.doc.toString() ?? props.content)
})

// `content` 从外部变化（切文件、冲突横幅[载入最新]）：只有和当前文档不一致
// 时才重建，避免把自己刚发出的 `update:content` 事件回声再重建一次。
watch(
  () => props.content,
  (next) => {
    if (!view) return
    if (view.state.doc.toString() !== next) createView(next)
  },
)
</script>

<template>
  <div
    ref="container"
    class="h-full min-h-[240px] overflow-auto rounded border font-mono text-sm [&_.cm-editor]:h-full"
  />
</template>
