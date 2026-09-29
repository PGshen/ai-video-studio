/**
 * 镜头状态计算（任务 T12，决策记录 D38）：镜头列表要展示"已有代码/还没有
 * 代码"——计划正文里"已渲染/已过期/校验失败"的完整状态在 M2 做不到：
 * `validate_scenes` 的结果只存在于对话事件流里，不落库（`agent/
 * turn_events.py` 只持久化 `tool_result` 的文本/是否出错，没有另建一张
 * "每个镜头最近一次校验结果"的表），`render_preview` 同理。M2 先按计划
 * 「接口与要点」里给出的退路，只用"`animation/scenes/<id>.py`
 * 是否存在"这一个信号；"已校验/已过期"的持久化状态跟踪记入技术债
 * （见决策记录），留给以后真的需要时再做。
 */

export interface SceneStatus {
  /** 叙事产物里的镜头 id，顺序与 `narrative.json` 一致。 */
  id: string
  /** 该镜头代码在工作区里的路径。 */
  path: string
  /** `animation/scenes/<id>.py` 当前是否已经存在（唯一支持的状态信号）。 */
  exists: boolean
}

export function scenePath(sceneId: string): string {
  return `animation/scenes/${sceneId}.py`
}

/**
 * @param sceneIds 从 `narrative.json` 解析出的镜头 id，按叙事顺序。
 * @param existingPaths 当前工作区文件树里的全部路径（`FileEntry.path`）。
 */
export function computeSceneStatuses(
  sceneIds: readonly string[],
  existingPaths: readonly string[],
): SceneStatus[] {
  const known = new Set(existingPaths)
  return sceneIds.map((id) => {
    const path = scenePath(id)
    return { id, path, exists: known.has(path) }
  })
}
