/**
 * 编辑器缓冲区的脏改动/冲突状态机（任务简报 T14，控制者裁定 3；设计
 * §6.4）：`workspace_changed` 让文件内容查询重新拉取，如果这时缓冲区有
 * 未保存的修改，不能直接用新内容覆盖用户还没保存的东西——要弹冲突横幅，
 * 让用户选[保留我的修改]或[载入最新]。
 *
 * 纯函数状态转换，`FileCanvas.vue` 是唯一调用方：
 * - `initBuffer(serverContent)`：切换文件/首次加载。
 * - `edit(state, content)`：用户在编辑器里敲字。
 * - `serverUpdate(state, newServerContent)`：文件内容查询重新拉取到新内容。
 *   缓冲区干净（没有未保存修改）时直接采用；缓冲区脏时不覆盖，进入
 *   `conflict` 态，把新内容存进 `incomingContent` 等用户选择。
 * - `keepMine(state)`：冲突横幅点[保留我的修改]——放弃这次服务器更新，
 *   但要把 `savedContent` 基线更新成 `incomingContent`，否则下次保存后
 *   `dirty` 的判断还是拿旧基线比较（新内容和旧基线可能碰巧相等，误判为
 *   "没有改动"）。
 * - `loadLatest(state)`：点[载入最新]——丢弃本地改动，采用服务器内容。
 * - `saved(state, savedContent)`：保存成功，新内容就是新基线。
 */

export interface BufferState {
  /** 编辑器里当前显示的内容。 */
  content: string
  /** 已知与服务器一致的基线：加载/保存成功/冲突时选择"保留我的修改"后更新。 */
  savedContent: string
  /** `content !== savedContent`。 */
  dirty: boolean
  /** 缓冲区脏时收到了服务器的新内容，等待用户选择。 */
  conflict: boolean
  /** 冲突态下服务器的新内容；非冲突态为 `null`。 */
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
  if (newServerContent === state.savedContent) return state // 不是真正的变化（比如自己刚保存触发的重新拉取）。
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
