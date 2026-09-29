/**
 * 从 `upstream/narrative/narrative.json` 的原始文本里解析出镜头 id 列表
 * （任务 T12，决策记录 D37）：后端没有专门"列出镜头"的端点（`stages/
 * animation/render_preview.py` 的决策记录也提到同样的判断——用 `dict`/
 * `TypedDict` 读取即可，不需要一个提前于 M3 的完整 narrative schema
 * 模块），前端这里同样只取 `scenes[].id`，按原始出现顺序返回，不关心
 * 其余字段（`narration`/`beats` 等）。
 *
 * `narrative.json` 本身解析失败（不是合法 JSON）时让 `JSON.parse` 的
 * `SyntaxError` 原样抛出，调用方（`AnimationCanvas.vue`）负责 try/catch
 * 并展示错误提示——这里只管"解析出来的结构对不对"，不管"字符串本身是不是
 * 合法 JSON"这类调用方已经能从异常类型分辨的情况。
 */

/** `upstream/narrative/narrative.json` 在工作区里的固定路径（叙事阶段定稿后，
 * `TurnRunner`/`turn_finish` 在每轮开始/结束前物化——`animation` 会话在第一轮
 * 对话真正跑起来之前，这个路径在文件树里还不存在，`AnimationCanvas.vue`
 * 据此展示"还没有物化"的提示，而不是当成解析错误处理）。 */
export const NARRATIVE_JSON_PATH = 'upstream/narrative/narrative.json'

interface RawNarrativeSceneRef {
  id?: unknown
}

interface RawNarrativeDoc {
  scenes?: unknown
}

export function parseNarrativeSceneIds(raw: string): string[] {
  const parsed = JSON.parse(raw) as RawNarrativeDoc
  if (!Array.isArray(parsed.scenes)) return []
  const ids: string[] = []
  for (const entry of parsed.scenes as RawNarrativeSceneRef[]) {
    if (entry !== null && typeof entry === 'object' && typeof entry.id === 'string') {
      ids.push(entry.id)
    }
  }
  return ids
}
