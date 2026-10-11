import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { VIDEO_KINDS_FIXTURE } from '@/test/videoKindsFixture'

const state = vi.hoisted(() => ({ mutateAsync: vi.fn(), push: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: state.push }) }))
vi.mock('@/composables/queries', () => ({
  useStylesQuery: () => ({ data: ref([]) }),
  useVideoKindsQuery: () => ({
    data: ref(VIDEO_KINDS_FIXTURE),
    isError: ref(false),
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

import NewFreeProjectDialog from './NewFreeProjectDialog.vue'

async function mountOpen() {
  const wrapper = mount(NewFreeProjectDialog, { props: { open: false }, attachTo: document.body })
  await wrapper.setProps({ open: true })
  await flushPromises()
  return wrapper
}

const $ = <T extends Element>(selector: string) => document.body.querySelector(selector) as T
const submitButton = () =>
  [...document.body.querySelectorAll('button')].find((b) =>
    b.textContent?.includes('创建项目'),
  ) as HTMLButtonElement

async function typeTitle(text: string) {
  const input = $<HTMLInputElement>('#new-free-project-title')
  input.value = text
  input.dispatchEvent(new Event('input'))
  await flushPromises()
}

beforeEach(() => {
  state.mutateAsync.mockReset()
  state.push.mockReset()
})

describe('NewFreeProjectDialog', () => {
  it('只列出三种自由形态，默认选中自由讲解', async () => {
    const wrapper = await mountOpen()
    const cards = [...document.body.querySelectorAll('[data-testid^="kind-card-"]')]
    expect(cards.map((c) => c.getAttribute('data-testid'))).toEqual([
      'kind-card-free-explainer_html',
      'kind-card-free-motion_reel',
      'kind-card-free-music_video',
    ])
    expect($('[data-testid="kind-card-free-explainer_html"]').getAttribute('aria-pressed')).toBe(
      'true',
    )
    wrapper.unmount()
  })

  it('没有标题时不能提交', async () => {
    const wrapper = await mountOpen()
    expect(submitButton().disabled).toBe(true)
    wrapper.unmount()
  })

  it('自由讲解选合成配乐：请求体是 mode=free 的讲解 + synth，没有 idea_id，成功后跳到唯一阶段', async () => {
    state.mutateAsync.mockResolvedValue({ id: 'p1', current_stage: 'free_explainer' })
    const wrapper = await mountOpen()
    await typeTitle('  为什么天是蓝的  ')
    const select = $<HTMLSelectElement>('[data-testid="music-select"]')
    select.value = 'synth'
    select.dispatchEvent(new Event('change'))
    await flushPromises()

    submitButton().click()
    await flushPromises()

    expect(state.mutateAsync).toHaveBeenCalledTimes(1)
    const body = state.mutateAsync.mock.calls[0][0]
    expect(body).toMatchObject({
      title: '为什么天是蓝的',
      mode: 'free',
      engine: 'html',
      narration: true,
      music_source: 'synth',
    })
    expect(body).not.toHaveProperty('idea_id')
    expect(state.push).toHaveBeenCalledWith('/projects/p1/free_explainer')
    wrapper.unmount()
  })
})
