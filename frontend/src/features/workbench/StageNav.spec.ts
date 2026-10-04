import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/composables/queries', async () => {
  const { ref } = await import('vue')
  return { useSuggestionSummaryQuery: () => ({ data: ref(undefined) }) }
})
// 两个对话框各自的数据请求不在这里测，换成只暴露 open 状态的桩。
function dialogStub(testId: string) {
  return {
    default: defineComponent({
      props: { open: Boolean },
      setup: (props) => () => h('div', { 'data-testid': testId, 'data-open': String(props.open) }),
    }),
  }
}
vi.mock('./ProjectSettingsDialog.vue', () => dialogStub('settings-dialog'))
vi.mock('./ProjectInfoDialog.vue', () => dialogStub('info-dialog'))

import StageNav from './StageNav.vue'

function mountNav(collapsed = false) {
  return mount(StageNav, {
    props: {
      projectId: 'p1',
      currentStage: 'animation',
      collapsed,
      stages: [
        { stage: 'topic', status: 'finalized', finalized_snapshot_id: null, based_on: {}, finalized_at: null },
      ],
    },
  })
}

describe('StageNav 的「项目」分组', () => {
  it('分组叫「项目」，下面是「设置」和「信息」两项', () => {
    const wrapper = mountNav()
    expect(wrapper.find('[data-testid="rail-group-项目"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="rail-group-操作"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="open-project-settings"]').text()).toBe('设置')
    expect(wrapper.get('[data-testid="open-project-info"]').text()).toBe('信息')
  })

  it('点「信息」只打开信息对话框，点「设置」只打开设置对话框', async () => {
    const wrapper = mountNav()
    await wrapper.get('[data-testid="open-project-info"]').trigger('click')
    expect(wrapper.get('[data-testid="info-dialog"]').attributes('data-open')).toBe('true')
    expect(wrapper.get('[data-testid="settings-dialog"]').attributes('data-open')).toBe('false')
    await wrapper.get('[data-testid="open-project-settings"]').trigger('click')
    expect(wrapper.get('[data-testid="settings-dialog"]').attributes('data-open')).toBe('true')
  })

  it('折叠时只剩图标，按钮仍可点', () => {
    const wrapper = mountNav(true)
    expect(wrapper.get('[data-testid="open-project-info"]').text()).toBe('')
    expect(wrapper.get('[data-testid="open-project-info"]').attributes('title')).toBe('信息')
  })
})
