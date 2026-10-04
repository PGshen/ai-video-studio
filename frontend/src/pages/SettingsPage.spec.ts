import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from '@/router'
import SettingsPage from './SettingsPage.vue'

describe('SettingsPage', () => {
  it('不再有「风格库」标签（风格库已是侧栏的一级菜单）', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/settings/models')
    const wrapper = mount(SettingsPage, { global: { plugins: [router], stubs: { RouterView: true } } })

    const labels = wrapper.findAll('nav a').map((a) => a.text())

    expect(labels).toEqual(['模型配置', '语音', '通用'])
  })
})
