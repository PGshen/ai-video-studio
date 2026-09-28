/**
 * `FinalRenderPanel.vue` 的按钮状态判断（任务 T13）。
 *
 * "渲染成片"按钮的禁用条件——决策记录（T13）：`validate_scenes` 的结果
 * 目前不落库（T12 决策记录 D38/技术债 TD-33），前端拿不到"上一次校验是否
 * 通过"这个信号，所以不做"上一次校验没过就禁用"这种前端猜测。参照 D4
 * "api 层是校验的唯一事实来源"的思路：`POST /render` 本身在动画阶段
 * `locked` 时会返回 4xx（`api/jobs.py::create_render_job_endpoint`），
 * 前端按钮只在两种前端就能确定的情况下禁用——"还没有任何镜头"（点了也没
 * 意义）和"已经有一个任务在 `queued`/`running`"（避免重复提交同一次渲染）
 * ——校验失败的 4xx 交给调用方展示错误提示，不在这里重新发明一套判断
 * 规则，避免和 D4 产生两套不一致的规则。
 *
 * "成片定稿"按钮只在任务 `done` 后可点（计划正文 T13 小节）。
 */

export type JobStatus = 'queued' | 'running' | 'done' | 'failed'

/** 任务是否仍在跑（还没有 `done`/`failed`）。 */
export function isJobInFlight(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running'
}

/**
 * @param sceneCount 当前镜头列表长度（`AnimationCanvas.vue` 的 `scenes`）。
 * @param jobStatus 当前渲染任务（如果有）的状态。
 */
export function isRenderButtonDisabled(params: {
  sceneCount: number
  jobStatus: string | null | undefined
}): boolean {
  if (params.sceneCount === 0) return true
  return isJobInFlight(params.jobStatus)
}

/** "成片定稿"按钮只在任务成功产出成片后可点。 */
export function canFinalize(jobStatus: string | null | undefined): boolean {
  return jobStatus === 'done'
}

/** 任务状态对应的中文短标签，展示在进度条旁边。 */
export function jobStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'queued':
      return '排队中'
    case 'running':
      return '渲染中'
    case 'done':
      return '已完成'
    case 'failed':
      return '失败'
    default:
      return ''
  }
}
