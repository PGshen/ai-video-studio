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
  it('只列出三种自由形态和完全自由，默认选中自由讲解', async () => {
    const wrapper = await mountOpen()
    const cards = [...document.body.querySelectorAll('[data-testid^="kind-card-"]')]
    expect(cards.map((c) => c.getAttribute('data-testid'))).toEqual([
      'kind-card-free-explainer_html',
      'kind-card-free-motion_reel',
      'kind-card-free-music_video',
      'kind-card-open',
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

  it('选完全自由：出现主题框、没有配乐选择，请求体只有 mode=open 与主题，不带形态字段', async () => {
    state.mutateAsync.mockResolvedValue({ id: 'p2', current_stage: 'open' })
    const wrapper = await mountOpen()
    expect(document.body.querySelector('#new-free-project-theme')).toBeNull()
    $<HTMLButtonElement>('[data-testid="kind-card-open"]').click()
    await flushPromises()
    expect(document.body.querySelector('[data-testid="music-select"]')).toBeNull()
    await typeTitle('标题动画')
    const theme = $<HTMLTextAreaElement>('#new-free-project-theme')
    expect(theme.maxLength).toBe(2000)
    theme.value = '  光的折射  '
    theme.dispatchEvent(new Event('input'))
    await flushPromises()

    submitButton().click()
    await flushPromises()

    const body = state.mutateAsync.mock.calls[0][0]
    expect(body).toMatchObject({ title: '标题动画', mode: 'open', theme: '光的折射' })
    for (const key of ['engine', 'narration', 'music_source']) expect(body).not.toHaveProperty(key)
    expect(state.push).toHaveBeenCalledWith('/projects/p2/open')
    wrapper.unmount()
  })

  it('完全自由不填主题时请求体不带 theme', async () => {
    state.mutateAsync.mockResolvedValue({ id: 'p3', current_stage: 'open' })
    const wrapper = await mountOpen()
    $<HTMLButtonElement>('[data-testid="kind-card-open"]').click()
    await flushPromises()
    await typeTitle('t')

    submitButton().click()
    await flushPromises()

    expect(state.mutateAsync.mock.calls[0][0]).not.toHaveProperty('theme')
    wrapper.unmount()
  })
})
