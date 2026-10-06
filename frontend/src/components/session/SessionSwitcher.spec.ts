import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SessionSwitcher from './SessionSwitcher.vue'

const api = vi.hoisted(() => ({
  listBrainstormSessions: vi.fn(),
  deleteSession: vi.fn(),
  listModelProfiles: vi.fn(async () => []),
  getSettings: vi.fn(async () => ({ stage_default_profile: {} })),
}))
vi.mock('@/api/endpoints', () => api)

const session = (id: string, title: string | null, active = false) => ({
  id,
  project_id: null,
  stage: 'brainstorm',
  subject_id: null,
  model_profile_id: 'p',
  runtime: 'fake',
  sdk_ref: null,
  status: 'idle',
  is_active: active,
  title,
})

function mountSwitcher() {
  return mount(SessionSwitcher, {
    props: { scope: { kind: 'brainstorm' as const }, sessionId: null },
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
    attachTo: document.body,
  })
}

describe('SessionSwitcher', () => {
  beforeEach(() => {
    api.listBrainstormSessions.mockResolvedValue([session('s1', 'A'), session('s2', null, true)])
    api.deleteSession.mockReset()
    api.deleteSession.mockResolvedValue(undefined)
  })

  it('默认选中活动会话，触发按钮显示它的标题', async () => {
    const w = mountSwitcher()
    await flushPromises()
    expect(w.emitted('update:sessionId')?.[0]).toEqual(['s2'])
    w.unmount()
  })

  it('没有会话时显示「还没有会话」且不选中任何会话', async () => {
    api.listBrainstormSessions.mockResolvedValue([])
    const w = mountSwitcher()
    await flushPromises()
    expect(w.get('[data-testid="session-switcher-trigger"]').text()).toBe('还没有会话')
    expect(w.emitted('update:sessionId')).toBeUndefined()
    w.unmount()
  })
})
