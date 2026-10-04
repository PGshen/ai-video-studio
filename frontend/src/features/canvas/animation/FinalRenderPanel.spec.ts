import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobOut } from '@/types/api'
import FinalRenderPanel from './FinalRenderPanel.vue'

const api = vi.hoisted(() => ({
  getLatestJob: vi.fn(),
  getJob: vi.fn(),
  getProject: vi.fn(),
}))

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  ...api,
}))

const doneJob: JobOut = {
  id: 'job-1',
  type: 'final_render',
  project_id: 'p1',
  status: 'done',
  progress: 1,
  error: null,
  result: { output_path: 'output/final.mp4' },
  created_at: '2026-10-03T16:23:10',
  updated_at: '2026-10-03T16:30:00',
}

function mountPanel(queryClient: QueryClient) {
  return mount(FinalRenderPanel, {
    props: { projectId: 'p1', sceneCount: 3 },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

describe('FinalRenderPanel 重新挂载', () => {
  beforeEach(() => {
    api.getLatestJob.mockReset().mockResolvedValue(doneJob)
    api.getJob.mockReset().mockResolvedValue(doneJob)
    api.getProject.mockReset().mockResolvedValue({ completed_at: null })
  })

  it('切走再回来：缓存里的最近任务和新查询结果一致时，仍然恢复出成片', async () => {
    const queryClient = new QueryClient()

    const first = mountPanel(queryClient)
    await flushPromises()
    expect(first.find('video').exists()).toBe(true)
    first.unmount()

    const second = mountPanel(queryClient)
    await flushPromises()
    expect(second.find('video').exists()).toBe(true)
  })

  it('缓存里的最近任务是旧的：以重新查询到的最新任务为准', async () => {
    const queryClient = new QueryClient()
    const olderJob = { ...doneJob, id: 'job-0' }
    api.getLatestJob.mockResolvedValueOnce(olderJob)
    api.getJob.mockImplementation(async (_p: string, id: string) =>
      id === 'job-1' ? doneJob : olderJob,
    )

    mountPanel(queryClient).unmount()
    await flushPromises()

    mountPanel(queryClient)
    await flushPromises()
    expect(api.getJob).toHaveBeenLastCalledWith('p1', 'job-1')
  })
})
