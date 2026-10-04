import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { VIDEO_KINDS_FIXTURE } from '@/test/videoKindsFixture'
import type { IdeaOut } from '@/types/api'

const state = vi.hoisted(() => ({
  kindsError: false,
  mutateAsync: vi.fn(),
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: state.push }) }))
vi.mock('@/composables/queries', () => ({
  useStylesQuery: () => ({ data: ref([]) }),
  useVideoKindsQuery: () => ({
    data: ref(state.kindsError ? undefined : VIDEO_KINDS_FIXTURE),
    isError: ref(state.kindsError),
    isPending: ref(false),
  }),
  useCreateProjectMutation: () => ({
    mutateAsync: state.mutateAsync,
    isPending: ref(false),
    isError: ref(false),
    error: ref(null),
    reset: vi.fn(),
  }),
}))

import CreateProjectDialog from './CreateProjectDialog.vue'

const idea = { id: 'i1', title: '黑洞' } as IdeaOut

async function mountOpen() {
  const wrapper = mount(CreateProjectDialog, {
    props: { idea, open: false },
    attachTo: document.body,
  })
  await wrapper.setProps({ open: true })
  await flushPromises()
  return wrapper
}

const submitButton = () =>
  [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('创建项目')) as HTMLButtonElement

beforeEach(() => {
  state.kindsError = false
  state.mutateAsync.mockReset()
  state.push.mockReset()
  document.body.innerHTML = ''
})

describe('CreateProjectDialog 视频类型', () => {
  it('提交请求体带 engine/narration/music_source，成功后跳到项目当前阶段', async () => {
    state.mutateAsync.mockResolvedValue({ id: 'p9', current_stage: 'concept' })
    const wrapper = await mountOpen()
    submitButton().click()
    await flushPromises()
    expect(state.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ engine: 'manim', narration: true, music_source: 'none', idea_id: 'i1' }),
    )
    expect(state.push).toHaveBeenCalledWith('/projects/p9/concept')
    wrapper.unmount()
  })

  it('video-kinds 加载失败时显示错误并禁用提交', async () => {
    state.kindsError = true
    const wrapper = await mountOpen()
    expect(document.body.textContent).toContain('视频类型加载失败')
    expect(submitButton().disabled).toBe(true)
    wrapper.unmount()
  })
})
