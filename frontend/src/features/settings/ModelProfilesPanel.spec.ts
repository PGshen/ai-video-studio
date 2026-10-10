import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ModelProfileOut, ModelProfileTestOut } from '@/types/api'
import ModelProfilesPanel from './ModelProfilesPanel.vue'

const api = vi.hoisted(() => ({
  listModelProfiles: vi.fn(),
  testModelProfile: vi.fn(),
}))

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  ...api,
}))

function profile(name: string): ModelProfileOut {
  return {
    id: `id-${name}`,
    name,
    provider: 'anthropic',
    model: 'm',
    runtime: 'claude',
    base_url: null,
    api_key_env: null,
    supports_vision: false,
    price_input: null,
    price_output: null,
    max_cost_per_turn: null,
    max_steps_per_turn: null,
    key_configured: true,
    builtin: true,
    env_override: [],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

function mountPanel() {
  return mount(ModelProfilesPanel, {
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
    attachTo: document.body,
  })
}

describe('ModelProfilesPanel 连通性测试', () => {
  beforeEach(() => {
    api.listModelProfiles.mockReset().mockResolvedValue([profile('a'), profile('b')])
    api.testModelProfile.mockReset()
  })

  it('点「测试」：按钮进入测试中，结果显示在这一行', async () => {
    const pending = deferred<ModelProfileTestOut>()
    api.testModelProfile.mockReturnValue(pending.promise)
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="test-a"]').trigger('click')

    expect(api.testModelProfile).toHaveBeenCalledWith('id-a')
    expect(wrapper.get('[data-testid="test-a"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="test-b"]').attributes('disabled')).toBeUndefined()

    pending.resolve({ ok: true, latency_ms: 1500, reply: 'ok', error: null })
    await flushPromises()

    expect(wrapper.get('[data-testid="test-a"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="probe-a"]').text()).toContain('连通 · 1.5s · ok')
    expect(wrapper.find('[data-testid="probe-b"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('失败结果用错误样式；请求本身出错时显示错误信息', async () => {
    api.testModelProfile
      .mockResolvedValueOnce({ ok: false, latency_ms: null, reply: null, error: '环境变量 K 未设置' })
      .mockRejectedValueOnce(new Error('网络断了'))
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="test-a"]').trigger('click')
    await wrapper.get('[data-testid="test-b"]').trigger('click')
    await flushPromises()

    const a = wrapper.get('[data-testid="probe-a"]')
    expect(a.text()).toContain('失败 · 环境变量 K 未设置')
    expect(a.classes()).toContain('text-destructive')
    expect(wrapper.get('[data-testid="probe-b"]').text()).toContain('网络断了')
    wrapper.unmount()
  })
})
