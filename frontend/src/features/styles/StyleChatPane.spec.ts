import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'

const state = vi.hoisted(() => ({ createSession: vi.fn(async () => 's-new') }))

vi.mock('@/components/session/useEnsureSession', () => ({
  useEnsureSession: (_scope: unknown, sessionId: { value: string | null }) => async () => {
    sessionId.value = await state.createSession()
    return sessionId.value
  },
}))
vi.mock('@/components/session/SessionPicker.vue', () => ({
  default: {
    name: 'SessionPickerStub',
    props: ['scope', 'sessionId'],
    emits: ['update:sessionId'],
    setup: (props: { scope?: unknown }, { emit }: { emit: (e: string, v: string) => void }) => () =>
      h('div', { 'data-testid': 'picker', 'data-scope': JSON.stringify(props.scope) }, [
        h('button', { 'data-testid': 'pick', onClick: () => emit('update:sessionId', 's-picked') }),
      ]),
  },
}))
vi.mock('@/components/session/SessionPanel.vue', () => ({
  default: {
    name: 'SessionPanelStub',
    props: ['sessionId', 'projectId', 'createSession', 'beforeSend'],
    emits: ['sent'],
    setup: (props: { sessionId?: string | null }, { emit }: { emit: (e: 'sent') => void }) => () =>
      h('div', { 'data-testid': 'panel', 'data-session': props.sessionId ?? '' }, [
        h('button', { 'data-testid': 'send', onClick: () => emit('sent') }),
      ]),
  },
}))

import StyleChatPane from './StyleChatPane.vue'

let queryClient: QueryClient
const mountPane = (props: Record<string, unknown> = {}) => {
  queryClient = new QueryClient()
  return mount(StyleChatPane, {
    props: { styleId: 'sty1', ...props },
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

describe('StyleChatPane', () => {
  it('用这套风格的范围选会话，对话面板没有项目', () => {
    const w = mountPane()
    expect(JSON.parse(w.get('[data-testid="picker"]').attributes('data-scope')!)).toEqual({
      kind: 'style',
      styleId: 'sty1',
    })
    const panel = w.getComponent({ name: 'SessionPanelStub' })
    expect(panel.props('projectId')).toBeNull()
    expect(w.text()).toContain('AI 对话')
  })

  it('选中的会话传给对话面板', async () => {
    const w = mountPane()
    expect(w.get('[data-testid="panel"]').attributes('data-session')).toBe('')

    await w.get('[data-testid="pick"]').trigger('click')

    expect(w.get('[data-testid="panel"]').attributes('data-session')).toBe('s-picked')
  })

  it('没有会话时第一次发送用默认模型建会话，并把新会话选中', async () => {
    const w = mountPane()
    const panel = w.getComponent({ name: 'SessionPanelStub' })

    await (panel.props('createSession') as () => Promise<string>)()
    await w.vm.$nextTick()

    expect(state.createSession).toHaveBeenCalledTimes(1)
    expect(w.get('[data-testid="panel"]').attributes('data-session')).toBe('s-new')
  })

  it('beforeSend 原样传给对话面板', () => {
    const beforeSend = vi.fn(async () => {})
    const w = mountPane({ beforeSend })
    expect(w.getComponent({ name: 'SessionPanelStub' }).props('beforeSend')).toBe(beforeSend)
  })

  it('换一套风格时清掉选中的会话', async () => {
    const w = mountPane()
    await w.get('[data-testid="pick"]').trigger('click')
    expect(w.get('[data-testid="panel"]').attributes('data-session')).toBe('s-picked')

    await w.setProps({ styleId: 'sty2' })

    expect(w.get('[data-testid="panel"]').attributes('data-session')).toBe('')
  })

  it('消息发出去之后立刻刷新草稿状态（新会话的第一轮时 SSE 可能还没连上，不能只靠流里的 turn_status）', async () => {
    const w = mountPane()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')

    await w.get('[data-testid="send"]').trigger('click')

    expect(spy.mock.calls.map((c) => c[0]?.queryKey)).toContainEqual(['styles', 'sty1', 'draft'])
  })
})
