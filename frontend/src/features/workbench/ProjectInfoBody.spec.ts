import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('@/composables/queries', () => ({
  useProjectQuery: () => ({
    data: ref({
      id: 'p1',
      title: '黑洞',
      idea_id: null,
      current_stage: 'topic',
      status: 'active',
      completed_at: null,
      abandoned_at: null,
      stages: [],
      kind: { video_kind: 'explainer_manim', engine: 'manim', narration: true, music_source: 'none', pipeline: ['topic'] },
    }),
  }),
  useAllIdeasQuery: () => ({ data: ref([]), isPending: ref(false) }),
  useFileTreeQuery: () => ({ data: ref({ files: [] }) }),
  useFileContentQuery: () => ({ data: ref(undefined) }),
}))
vi.mock('@/components/ProjectStatusMenu.vue', () => ({ default: { template: '<span />' } }))

import ProjectInfoBody from './ProjectInfoBody.vue'

describe('ProjectInfoBody', () => {
  it('基本信息里显示视频类型摘要', () => {
    const w = mount(ProjectInfoBody, { props: { projectId: 'p1' } })
    expect(w.get('[data-testid="project-info-kind"]').text()).toBe('知识讲解（Manim）· 有旁白 · 无配乐')
  })
})
