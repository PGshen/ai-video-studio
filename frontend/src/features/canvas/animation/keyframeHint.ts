/**
 * `KeyframeStrip.vue` 显示的提示文案（任务 T12，决策记录 D39）：
 * `render_preview` 产生的关键帧图片本身走对话事件流（`agent/events.py`
 * 的 `ImageData` 作为工具结果的一部分），但 `agent/turn_events.py::handle`
 * 落库/推送 `tool_result` 事件时只保留每张图的 `media_type`，**不**保留
 * `data_base64`（代码里的注释原文："Image payloads are not persisted,
 * only their types."）——这是 M1 就登记的技术债 TD-21，"来源"一栏写的是
 * "M2 处理"但没有指定具体任务号；本任务判断不在 T12 里顺带修（需要改
 * `turn_events.py` 的持久化格式，甚至给图片内容找个存放位置——超出 T12
 * "涉及文件"列的前端范围，属于"计划之外的公共接口改动"，见 AGENTS.md
 * 红线），继续留给以后处理 TD-21 时解决。
 *
 * 因此这里不做"拉取并显示缩略图"（数据源头就没有字节内容），只做一句
 * 静态提示，指向真正能看到信息的地方——左侧对话面板的工具结果卡片
 * （`SessionTimelineItem.vue` 已经会显示"含 N 张图片"的计数）。这也回答了
 * 计划里留的判断题："前端画布是否需要单独重新拉取关键帧的按钮"——不需要，
 * 现有 SSE 事件流（`tool_result.images` 计数）已经是能拿到的全部信息，
 * 加一条新端点也拿不到更多东西。
 */

export function keyframeHint(sceneId: string | null): string {
  if (sceneId === null) {
    return '选择一个镜头后，这里会提示怎么预览它的关键帧。'
  }
  return (
    `在左侧对话里让 agent 对镜头「${sceneId}」调用 render_preview 工具：` +
    '关键帧张数和渲染/配音时长偏差会出现在对话的工具结果里。' +
    '当前版本图片内容还没有持久化（技术债 TD-21），这里和对话里都只能看到数量，看不到缩略图。'
  )
}
