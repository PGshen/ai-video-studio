import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import type { ProjectOut } from '@/types/api'

const state = vi.hoisted(() => ({ projects: [] as unknown[] }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/projects', query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
}))
vi.mock('@/composables/queries', () => ({
  useProjectsQuery: () => ({ data: ref(state.projects), isPending: ref(false), isError: ref(false) }),
  useAllIdeasQuery: () => ({ data: ref([]) }),
  useDeleteProjectMutation: () => ({ mutateAsync: vi.fn(), isPending: ref(false) }),
  useSetProjectStatusMutation: () => ({ mutate: vi.fn(), isPending: ref(false) }),
}))
vi.mock('./NewFreeProjectDialog.vue', () => ({
  default: defineComponent({
    props: { open: Boolean },
    setup: (props) => () => h('div', { 'data-testid': 'new-dialog', 'data-open': String(props.open) }),
  }),
}))

import ProjectList from './ProjectList.vue'

function project(id: string, mode: 'staged' | 'free' | 'open', stage: string): ProjectOut {
  return {
    id,
    title: `项目 ${id}`,
    idea_id: null,
    current_stage: stage,
    settings: {},
    completed_at: null,
    abandoned_at: null,
    status: 'active',
    kind: {
      video_kind: 'motion_reel',
      engine: 'html',
      narration: false,
      music_source: 'synth',
      mode,
      pipeline: [stage],
    },
  }
}

describe('ProjectList', () => {
  it('空列表提示可以新建，也可以从选题卡片创建', async () => {
    state.projects = []
    const wrapper = mount(ProjectList)
    await flushPromises()
    expect(wrapper.text()).toContain('新建一个项目，或从「选题」的卡片创建')
  })

  it('「新建项目」按钮打开新建对话框', async () => {
    state.projects = []
    const wrapper = mount(ProjectList)
    expect(wrapper.get('[data-testid="new-dialog"]').attributes('data-open')).toBe('false')
    await wrapper.get('[data-testid="new-project"]').trigger('click')
    expect(wrapper.get('[data-testid="new-dialog"]').attributes('data-open')).toBe('true')
  })

  it('自由项目的卡片带「自由」标记，阶段名是「自由创作」', async () => {
    state.projects = [project('a', 'free', 'free_produce'), project('b', 'staged', 'concept')]
    const wrapper = mount(ProjectList)
    await flushPromises()
    const free = wrapper.get('[data-testid="project-card-a"]')
    expect(free.find('[data-testid="free-badge"]').exists()).toBe(true)
    expect(free.text()).toContain('自由创作')
    expect(wrapper.get('[data-testid="project-card-b"]').find('[data-testid="free-badge"]').exists()).toBe(
      false,
    )
  })

  it('完全自由项目的卡片阶段名是「完全自由」，不带「自由」标记', async () => {
    state.projects = [project('c', 'open', 'open')]
    const wrapper = mount(ProjectList)
    await flushPromises()
    const card = wrapper.get('[data-testid="project-card-c"]')
    expect(card.text()).toContain('完全自由')
    expect(card.find('[data-testid="free-badge"]').exists()).toBe(false)
  })
})
