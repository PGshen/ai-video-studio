/**
 * 镜头状态计算（任务 T12，决策记录 D38；TD-33 修复后扩展）：镜头列表要展示
 * "已有代码/还没有代码"（`exists`，来自文件树），以及"已校验通过/校验
 * 失败/已过期/没检查过"（`validateScenes`/`renderPreview`，来自
 * `GET /projects/{id}/animation/scene-checks` 的读模型，见
 * `api/scene_checks.py`）。检查数据是异步拉取的，拉到之前或者这个镜头
 * 从没被检查过时对应字段是 `null`。
 */

import type { SceneChecksOut, SceneChecksResponse, SceneCheckOut } from '@/types/api'

export interface SceneStatus {
  /** 叙事产物里的镜头 id，顺序与 `narrative.json` 一致。 */
  id: string
  /** 该镜头代码在工作区里的路径。 */
  path: string
  /** `animation/scenes/<id>.py` 当前是否已经存在。 */
  exists: boolean
  /** 最近一次 `validate_scenes` 里这个镜头的状态；没检查过是 `null`。 */
  validateScenes: SceneCheckOut | null
  /** 最近一次 `render_preview` 的状态；没检查过是 `null`。 */
  renderPreview: SceneCheckOut | null
}

export function scenePath(sceneId: string): string {
  return `animation/scenes/${sceneId}.py`
}

/**
 * @param sceneIds 从 `narrative.json` 解析出的镜头 id，按叙事顺序。
 * @param existingPaths 当前工作区文件树里的全部路径（`FileEntry.path`）。
 * @param checks `useSceneChecksQuery` 拉到的读模型；未传或还没拉到时全部
 *   镜头的 `validateScenes`/`renderPreview` 都是 `null`。
 */
export function computeSceneStatuses(
  sceneIds: readonly string[],
  existingPaths: readonly string[],
  checks?: SceneChecksResponse['scenes'],
): SceneStatus[] {
  const known = new Set(existingPaths)
  return sceneIds.map((id) => {
    const path = scenePath(id)
    const check: SceneChecksOut | undefined = checks?.[id]
    return {
      id,
      path,
      exists: known.has(path),
      validateScenes: check?.validate_scenes ?? null,
      renderPreview: check?.render_preview ?? null,
    }
  })
}
