import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  log: [] as string[],
  sentWith: [] as Array<{ sessionId: string; text: string }>,
  turnStatus: null as { status: string; turnId: string } | null,
}))

vi.mock('@/composables/useSessionStream', async () => {
  const { ref: vueRef } = await import('vue')
  return {
    useSessionStream: () => ({
      items: vueRef([]),
      turnStatus: vueRef(state.turnStatus),
      turns: vueRef(new Map()),
      addLocalUserMessage: (text: string) => {
        state.log.push(`add:${text}`)
        return 'local-1'
      },
      markTurnAccepted: () => {},
      removeLocalUserMessage: () => {
        state.log.push('remove')
      },
    }),
  }
})
vi.mock('@/composables/queries', () => ({
  useSendMessageMutation: (sessionId: () => string) => ({
    mutateAsync: async (body: { text: string }) => {
      state.log.push('send')
      state.sentWith.push({ sessionId: sessionId(), text: body.text })
      return { turn_id: 't1' }
    },
  }),
  useCancelSessionMutation: () => ({ mutateAsync: async () => {} }),
  useContinueSessionMutation: () => ({ mutateAsync: async () => ({ turn_id: 't2' }) }),
}))
vi.mock('./SessionTimeline.vue', () => ({ default: { name: 'SessionTimeline', render: () => null } }))

import SessionPanel from './SessionPanel.vue'

const textarea = (w: ReturnType<typeof mountPanel>) => w.get('textarea[name="message"]')

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(SessionPanel, {
    props: { sessionId: null, projectId: 'p1', ...props },
    attachTo: document.body,
  })
}

async function submit(w: ReturnType<typeof mountPanel>, text: string) {
  await textarea(w).setValue(text)
  await w.get('form').trigger('submit')
  await flushPromises()
}

describe('SessionPanel：没有会话时发送', () => {
  beforeEach(() => {
    state.log = []
    state.sentWith = []
    document.body.innerHTML = ''
  })

  it('没有会话、也没给 createSession：输入框和发送按钮禁用', () => {
    const w = mountPanel()
    expect(textarea(w).attributes('disabled')).toBeDefined()
    expect(w.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('没有会话但给了 createSession：输入框可用', () => {
    const w = mountPanel({ createSession: vi.fn() })
    expect(textarea(w).attributes('disabled')).toBeUndefined()
  })

  it('第一次发送先建会话，等会话 id 传进来后再乐观插入并发送', async () => {
    const w = mountPanel()
    const createSession = vi.fn(async () => {
      state.log.push('create')
      await w.setProps({ sessionId: 'new-session' })
      return 'new-session'
    })
    await w.setProps({ createSession })
    await submit(w, '你好')
    expect(createSession).toHaveBeenCalledTimes(1)
    expect(state.log).toEqual(['create', 'add:你好', 'send'])
    expect(state.sentWith).toEqual([{ sessionId: 'new-session', text: '你好' }])
  })

  it('已有会话时不再建会话', async () => {
    const createSession = vi.fn()
    const w = mountPanel({ sessionId: 's1', createSession })
    await submit(w, '你好')
    expect(createSession).not.toHaveBeenCalled()
    expect(state.sentWith).toEqual([{ sessionId: 's1', text: '你好' }])
  })

  it('建会话失败：显示错误，不发送、不留乐观消息', async () => {
    const createSession = vi.fn(async () => {
      throw new Error('没有已配置密钥的模型')
    })
    const w = mountPanel({ createSession })
    await submit(w, '你好')
    expect(w.text()).toContain('没有已配置密钥的模型')
    expect(state.log).toEqual([])
    expect(state.sentWith).toEqual([])
  })
})

describe('SessionPanel：sending 事件', () => {
  beforeEach(() => {
    state.log = []
    state.sentWith = []
    document.body.innerHTML = ''
  })

  const listeners = () => ({
    onSending: (value: boolean) => state.log.push(`sending:${value}`),
    onSent: () => state.log.push('sent'),
  })

  it('点发送起（beforeSend 之前）发 sending(true)，发送成功后先 sent 再 sending(false)', async () => {
    const beforeSend = vi.fn(async () => {
      state.log.push('before')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend, ...listeners() })

    await submit(w, '你好')

    expect(state.log).toEqual(['sending:true', 'before', 'add:你好', 'send', 'sent', 'sending:false'])
  })

  it('beforeSend 失败：sending(false) 照发，没有 sent', async () => {
    const beforeSend = vi.fn(async () => {
      throw new Error('草稿还没有写入成功')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend, ...listeners() })

    await submit(w, '你好')

    expect(state.log).toEqual(['sending:true', 'sending:false'])
  })

  it('点 [继续] 同样：sending(true) → 乐观消息 → sent → sending(false)', async () => {
    state.turnStatus = { status: 'interrupted', turnId: 't0' }
    try {
      const w = mountPanel({ sessionId: 's1', ...listeners() })
      const button = w.findAll('button').find((b) => b.text() === '继续')!
      await button.trigger('click')
      await flushPromises()

      expect(state.log).toEqual(['sending:true', 'add:继续', 'sent', 'sending:false'])
    } finally {
      state.turnStatus = null
    }
  })

  it('输入为空什么都不发', async () => {
    const w = mountPanel({ sessionId: 's1', ...listeners() })

    await submit(w, '   ')

    expect(state.log).toEqual([])
  })
})

describe('SessionPanel：beforeSend', () => {
  beforeEach(() => {
    state.log = []
    state.sentWith = []
    document.body.innerHTML = ''
  })

  it('发送前先调用 beforeSend（风格编辑用它把还没写出的编辑写进草稿）', async () => {
    const beforeSend = vi.fn(async () => {
      state.log.push('before')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend })

    await submit(w, '把配色改深一点')

    expect(beforeSend).toHaveBeenCalledTimes(1)
    expect(state.log).toEqual(['before', 'add:把配色改深一点', 'send'])
  })

  it('beforeSend 失败时不发送，显示原因', async () => {
    const beforeSend = vi.fn(async () => {
      throw new Error('草稿还没有写入成功')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend })

    await submit(w, '你好')

    expect(state.sentWith).toEqual([])
    expect(w.text()).toContain('草稿还没有写入成功')
  })

  it('没给 beforeSend 时行为不变', async () => {
    const w = mountPanel({ sessionId: 's1' })
    await submit(w, '你好')
    expect(state.sentWith).toEqual([{ sessionId: 's1', text: '你好' }])
  })
})
