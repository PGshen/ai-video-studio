import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('@/composables/queries', () => ({
  useProjectQuery: () => ({
    data: ref({
      id: 'p1',
      settings: {},
      busy: false,
      kind: { video_kind: 'explainer_manim', engine: 'manim', narration: true, music_source: 'none', pipeline: ['topic'] },
    }),
  }),
  useVoicesQuery: () => ({ data: ref([]) }),
  usePatchProjectSettingsMutation: () => ({
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPending: ref(false),
    error: ref(null),
  }),
}))
vi.mock('@/components/VoicePreviewButton.vue', () => ({ default: { template: '<span />' } }))

import ProjectSettingsDialog from './ProjectSettingsDialog.vue'

describe('ProjectSettingsDialog 视频类型', () => {
  it('顶部只读显示类型摘要和说明，没有可编辑的类型控件', async () => {
    document.body.innerHTML = ''
    const w = mount(ProjectSettingsDialog, { props: { projectId: 'p1', open: false }, attachTo: document.body })
    await w.setProps({ open: true })
    await flushPromises()
    const row = document.body.querySelector('[data-testid="project-kind"]')!
    expect(row.textContent).toContain('知识讲解（Manim）· 有旁白 · 无配乐')
    expect(row.textContent).toContain('创建后不能修改，换类型请新建项目')
    expect(row.querySelector('input,select,button')).toBeNull()
    w.unmount()
  })
})
