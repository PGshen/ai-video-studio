/**
 * 镜头代码编辑器缓冲区的脏改动/冲突状态机（任务 T12，决策记录 D36）：
 * 和 `features/canvas/generic/conflictState.ts` 逻辑完全一样（`animation`
 * 阶段的 agent 会用 `Write`/`Edit` 类工具写 `animation/scenes/*.py`，用户
 * 同时在画布里编辑同一个文件时会遇到和通用文件画布一样的冲突场景），但
 * ESLint 的 `features/* 之间互不 import` 规则不允许这个模块跨阶段画布
 * 复用（已用探针文件对 `pnpm lint` 实测确认）。这段状态机足够小、足够
 * 稳定（通用文件画布那份已经在用，行为不会再变），复制一份本地维护比
 * 为了单单这一段逻辑把 `components/`/`composables/` 变成"业务状态机的
 * 公共仓库"更清楚——参照 T7/T8 决策记录 D25/D26"测试文件各自定义一份本地
 * Protocol，不跨文件 import"同样的取舍。
 *
 * - `initBuffer(serverContent)`：切换镜头/首次加载。
 * - `edit(state, content)`：用户在编辑器里敲字。
 * - `serverUpdate(state, newServerContent)`：文件内容查询重新拉取到新内容
 *   （`workspace_changed` 触发）。缓冲区干净时直接采用；脏时不覆盖，进入
 *   `conflict` 态，把新内容存进 `incomingContent` 等用户选择。
 * - `keepMine(state)`：冲突横幅点[保留我的修改]。
 * - `loadLatest(state)`：点[载入最新]，丢弃本地改动。
 * - `saved(state, savedContent)`：保存成功，新内容就是新基线。
 */

export interface BufferState {
  content: string
  savedContent: string
  dirty: boolean
  conflict: boolean
  incomingContent: string | null
}

export function initBuffer(serverContent: string): BufferState {
  return {
    content: serverContent,
    savedContent: serverContent,
    dirty: false,
    conflict: false,
    incomingContent: null,
  }
}

export function edit(state: BufferState, content: string): BufferState {
  return { ...state, content, dirty: content !== state.savedContent }
}

export function serverUpdate(state: BufferState, newServerContent: string): BufferState {
  if (newServerContent === state.savedContent) return state
  if (!state.dirty) {
    return initBuffer(newServerContent)
  }
  return { ...state, conflict: true, incomingContent: newServerContent }
}

export function keepMine(state: BufferState): BufferState {
  if (!state.conflict) return state
  return {
    content: state.content,
    savedContent: state.incomingContent ?? state.savedContent,
    dirty: true,
    conflict: false,
    incomingContent: null,
  }
}

export function loadLatest(state: BufferState): BufferState {
  if (!state.conflict || state.incomingContent === null) return initBuffer(state.content)
  return initBuffer(state.incomingContent)
}

export function saved(state: BufferState, savedContent: string): BufferState {
  return initBuffer(savedContent)
}
