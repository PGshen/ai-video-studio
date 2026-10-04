/**
 * `CodeEditor.vue` 支持的语言标识（T12 从 `features/canvas/generic/fileKind.ts`
 * 拆出来，决策记录 D36）：`CodeEditor.vue` 本来和 `fileKind.ts` 同在
 * `features/canvas/generic/` 下，`animation` 画布要复用这个编辑器组件时，
 * ESLint 的 `features/* 之间互不 import` 规则会挡住跨阶段画布互相
 * import——实测（`pnpm lint` 对着一个探针文件跑过一次）确认这条规则按
 * `@/features/**` 整体匹配，不区分是不是同一个上级目录（`canvas/`）。
 *
 * 解法：把编辑器组件本身挪到 `components/`（规则允许 `features/*` 单向
 * import `components/`），这个类型跟着挪出来，`fileKind.ts` 改成从这里
 * import 再重新导出，保持自己现有的对外接口不变。
 */
export type EditorLanguage = 'markdown' | 'json' | 'python' | 'javascript' | 'text'
