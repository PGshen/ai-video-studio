/**
 * `KeyframeStrip.vue` 显示的提示文案（任务 T12，决策记录 D39；TD-21 修复
 * 后更新）：`render_preview` 产生的关键帧图片现在会持久化到 blob 库
 * （`agent/turn_events.py::_persist_image`），左侧对话面板的工具结果卡片
 * 里能看到真缩略图（`SessionTimelineItem.vue`）。
 *
 * 这里仍然只做文字提示、不在画布里单独拉一份"按镜头 id 聚合的关键帧
 * 画廊"：后端没有"某个镜头最近一次 render_preview 结果"这种读模型
 * （TD-33），要做真正嵌入画布的缩略图需要先解决那条技术债，不在这里
 * 顺手做。
 */

export function keyframeHint(sceneId: string | null): string {
  if (sceneId === null) {
    return '选择一个镜头后，这里会提示怎么预览它的关键帧。'
  }
  return (
    `在左侧对话里让 agent 对镜头「${sceneId}」调用 render_preview 工具：` +
    '关键帧缩略图、渲染/配音时长偏差会出现在对话的工具结果里。'
  )
}
