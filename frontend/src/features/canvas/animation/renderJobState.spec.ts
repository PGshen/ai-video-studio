import { describe, expect, it } from 'vitest'
import { canFinalize, isJobInFlight, isRenderButtonDisabled, jobStatusLabel } from './renderJobState'

describe('isJobInFlight', () => {
  it('queued/running 视为仍在跑', () => {
    expect(isJobInFlight('queued')).toBe(true)
    expect(isJobInFlight('running')).toBe(true)
  })

  it('done/failed/没有任务视为不在跑', () => {
    expect(isJobInFlight('done')).toBe(false)
    expect(isJobInFlight('failed')).toBe(false)
    expect(isJobInFlight(null)).toBe(false)
    expect(isJobInFlight(undefined)).toBe(false)
  })
})

describe('isRenderButtonDisabled', () => {
  it('没有镜头时禁用，即使没有任务在跑', () => {
    expect(isRenderButtonDisabled({ sceneCount: 0, jobStatus: null })).toBe(true)
  })

  it('有镜头、没有任务在跑时可点', () => {
    expect(isRenderButtonDisabled({ sceneCount: 2, jobStatus: null })).toBe(false)
    expect(isRenderButtonDisabled({ sceneCount: 2, jobStatus: 'done' })).toBe(false)
    expect(isRenderButtonDisabled({ sceneCount: 2, jobStatus: 'failed' })).toBe(false)
  })

  it('有镜头但已有任务 queued/running 时禁用，避免重复提交', () => {
    expect(isRenderButtonDisabled({ sceneCount: 2, jobStatus: 'queued' })).toBe(true)
    expect(isRenderButtonDisabled({ sceneCount: 2, jobStatus: 'running' })).toBe(true)
  })
})

describe('canFinalize', () => {
  it('只有任务 done 时才能定稿', () => {
    expect(canFinalize('done')).toBe(true)
    expect(canFinalize('queued')).toBe(false)
    expect(canFinalize('running')).toBe(false)
    expect(canFinalize('failed')).toBe(false)
    expect(canFinalize(null)).toBe(false)
    expect(canFinalize(undefined)).toBe(false)
  })
})

describe('jobStatusLabel', () => {
  it('覆盖 queued → running → done/failed 四种状态的展示文案', () => {
    expect(jobStatusLabel('queued')).toBe('排队中')
    expect(jobStatusLabel('running')).toBe('渲染中')
    expect(jobStatusLabel('done')).toBe('已完成')
    expect(jobStatusLabel('failed')).toBe('失败')
  })

  it('没有任务时返回空字符串', () => {
    expect(jobStatusLabel(null)).toBe('')
    expect(jobStatusLabel(undefined)).toBe('')
  })
})
