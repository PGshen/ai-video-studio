import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/http'
import type { VoiceOut } from '@/types/api'
import VoicePanel from './VoicePanel.vue'

const api = vi.hoisted(() => ({
  listVoices: vi.fn(),
  getSettings: vi.fn(),
  createVoice: vi.fn(),
  deleteVoice: vi.fn(),
}))

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  ...api,
}))

function voice(alias: string, engine = 'doubao_2.0'): VoiceOut {
  return { alias, label: `名-${alias}`, gender: 'female', speaker_id: `spk_${alias}`, engine }
}

const SETTINGS = { tts_default: { voice: 'zizi', speech_rate: 1 } }

function mountPanel() {
  return mount(VoicePanel, {
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
    attachTo: document.body,
  })
}

function field(testid: string): HTMLInputElement | HTMLSelectElement {
  return document.body.querySelector(`[data-testid="${testid}"]`) as HTMLInputElement
}

async function type(testid: string, value: string): Promise<void> {
  const el = field(testid)
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
  await flushPromises()
}

async function click(testid: string): Promise<void> {
  field(testid).click()
  await flushPromises()
}

describe('VoicePanel 音色管理', () => {
  beforeEach(() => {
    api.listVoices.mockReset().mockResolvedValue([voice('sisi', 'doubao_1.0'), voice('zizi')])
    api.getSettings.mockReset().mockResolvedValue(SETTINGS)
    api.createVoice.mockReset().mockImplementation(async (body: VoiceOut) => body)
    api.deleteVoice.mockReset().mockResolvedValue(undefined)
  })
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('每个音色显示豆包版本徽标', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.get('[data-testid="engine-sisi"]').text()).toBe('豆包 v1')
    expect(wrapper.get('[data-testid="engine-zizi"]').text()).toBe('豆包 v2')
    wrapper.unmount()
  })

  it('新增：校验失败不提交；通过后带上版本提交并刷新列表', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-testid="add-voice"]').trigger('click')
    await flushPromises()

    await click('voice-submit')
    expect(api.createVoice).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('名称不能为空')

    await type('voice-label', '新音色')
    await type('voice-alias', 'new_one')
    await type('voice-speaker', 'zh_male_x_moon_bigtts')
    await type('voice-engine', 'doubao_1.0')
    await type('voice-gender', 'male')
    api.listVoices.mockResolvedValue([voice('zizi'), voice('new_one', 'doubao_1.0')])
    await click('voice-submit')

    expect(api.createVoice).toHaveBeenCalledWith({
      alias: 'new_one',
      label: '新音色',
      gender: 'male',
      speaker_id: 'zh_male_x_moon_bigtts',
      engine: 'doubao_1.0',
    })
    expect(field('voice-submit')).toBeNull()
    expect(wrapper.find('[data-testid="voice-new_one"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('新增时别名与已有音色重复：本地拦截', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-testid="add-voice"]').trigger('click')
    await flushPromises()

    await type('voice-label', 'x')
    await type('voice-alias', 'zizi')
    await type('voice-speaker', 'spk')
    await click('voice-submit')

    expect(api.createVoice).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('别名已被占用')
    wrapper.unmount()
  })

  it('新增失败（409）：对话框保持打开并显示原因', async () => {
    api.createVoice.mockRejectedValue(new ApiError(409, '已有同名的音色别名：new_one'))
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-testid="add-voice"]').trigger('click')
    await flushPromises()
    await type('voice-label', 'x')
    await type('voice-alias', 'new_one')
    await type('voice-speaker', 'spk')

    await click('voice-submit')

    expect(field('voice-dialog-error').textContent).toContain('已有同名的音色别名')
    wrapper.unmount()
  })

  it('删除：要确认；成功后关闭对话框并刷新列表', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="delete-voice-sisi"]').trigger('click')
    await flushPromises()
    expect(api.deleteVoice).not.toHaveBeenCalled()
    api.listVoices.mockResolvedValue([voice('zizi')])
    await click('confirm-delete-voice')

    expect(api.deleteVoice).toHaveBeenCalledWith('sisi')
    expect(field('confirm-delete-voice')).toBeNull()
    expect(wrapper.find('[data-testid="voice-sisi"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('删除被拒绝（409）：对话框保持打开并原样显示原因', async () => {
    api.deleteVoice.mockRejectedValue(new ApiError(409, '音色 zizi 是新项目的默认音色，不能删除'))
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="delete-voice-zizi"]').trigger('click')
    await flushPromises()
    await click('confirm-delete-voice')

    expect(field('delete-voice-error').textContent).toContain('默认音色')
    expect(wrapper.find('[data-testid="voice-zizi"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
